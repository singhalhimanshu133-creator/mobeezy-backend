import db_core
import datetime
import os
import base64
from pathlib import Path
import hashlib
import json
import math

# ==========================================
# STORAGE PROVIDERS (CLOUD READY)
# ==========================================
class StorageProvider:
    def save(self, folder, filename, b64_data): raise NotImplementedError
    def list_files(self, folder): raise NotImplementedError
    def delete(self, folder, filename): raise NotImplementedError
    def get_file_b64(self, folder, filename): raise NotImplementedError

class LocalStorageProvider(StorageProvider):
    def __init__(self, base_dir="images"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
    def save(self, folder, filename, b64_data):
        p = self.base_dir / folder
        p.mkdir(parents=True, exist_ok=True)
        file_path = p / filename
        data = b64_data.split(",")[1] if "," in b64_data else b64_data
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(data))
        return f"{self.base_dir.name}/{folder}/"

    def list_files(self, folder):
        p = self.base_dir / folder
        if not p.exists(): return []
        return [f.name for f in p.iterdir() if f.is_file()]

    def delete(self, folder, filename):
        file_path = self.base_dir / folder / filename
        if file_path.exists(): file_path.unlink()
        return True

    def get_file_b64(self, folder, filename):
        file_path = self.base_dir / folder / filename
        if file_path.exists():
            with open(file_path, "rb") as f:
                ext = file_path.suffix.lower().replace('.', '')
                mime = f"image/{ext}" if ext in ['png','jpg','jpeg','gif'] else "image/png"
                return f"data:{mime};base64," + base64.b64encode(f.read()).decode('utf-8')
        return ""

class SupabaseStorageProvider(StorageProvider):
    def __init__(self, bucket_name="product-images"):
        self.bucket = bucket_name
        
    def save(self, folder, filename, b64_data):
        try:
            if not db_core.supabase: return ""
            data = base64.b64decode(b64_data.split(",")[1] if "," in b64_data else b64_data)
            path_on_supa = f"{folder}/{filename}"
            try:
                db_core.supabase.storage.from_(self.bucket).remove([path_on_supa])
            except:
                pass
            db_core.supabase.storage.from_(self.bucket).upload(path_on_supa, data)
            return f"{self.bucket}/{folder}/"
        except Exception as e:
            print("Storage Save Error:", e)
            return ""
            
    def list_files(self, folder):
        try:
            if not db_core.supabase: return []
            res = db_core.supabase.storage.from_(self.bucket).list(folder)
            return [f['name'] for f in res if f['name'] != '.emptyFolderPlaceholder']
        except: return []
        
    def delete(self, folder, filename):
        try:
            if not db_core.supabase: return False
            db_core.supabase.storage.from_(self.bucket).remove([f"{folder}/{filename}"])
            return True
        except: return False
        
    def get_file_b64(self, folder, filename):
        try:
            if not db_core.supabase: return ""
            res = db_core.supabase.storage.from_(self.bucket).download(f"{folder}/{filename}")
            b64 = base64.b64encode(res).decode('utf-8')
            ext = filename.split('.')[-1].lower()
            mime = f"image/{ext}" if ext in ['png','jpg','jpeg','gif'] else "image/png"
            return f"data:{mime};base64,{b64}"
        except: return ""

# ==========================================
# API BRIDGE CLASS (BUG FIXED)
# ==========================================
class APIBridge:
    def __init__(self):
        self.storage_mode = 'cloud' 
        self.storage = LocalStorageProvider() if self.storage_mode == 'local' else SupabaseStorageProvider()

        if 'AdminNotifications' not in db_core.SCHEMAS:
            db_core.SCHEMAS['AdminNotifications'] = ['Notif ID', 'Date Time', 'Message', 'Is Read']

        if 'ProductRateMapping' in db_core.SCHEMAS and 'Material' not in db_core.SCHEMAS['ProductRateMapping']:
            db_core.SCHEMAS['ProductRateMapping'] = ['Customer ID', 'Universal Name', 'Material', 'Rate']

    def _generate_new_id(self, items, id_key, prefix, padding):
        max_num = 0
        for item in items:
            val = str(item.get(id_key, ""))
            if val.startswith(prefix):
                try:
                    num_part = val.replace(prefix, "")
                    if "-" in num_part:
                        num_part = num_part.split("-")[0]
                    num = int(num_part)
                    if num > max_num:
                        max_num = num
                except:
                    pass
        return f"{prefix}{max_num + 1:0{padding}d}"

    def _sanitize_data(self, data):
        if isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        elif isinstance(data, dict):
            return {str(k): self._sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, (datetime.datetime, datetime.date)):
            return data.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(data, float):
            if math.isnan(data) or math.isinf(data): return 0.0
            return data
        else:
            return data

    def _safe_float(self, val):
        try:
            if val in [None, "", " ", "N/A", "null"]: return 0.0
            return float(val)
        except: return 0.0

    def _safe_int(self, val):
        try:
            if val in [None, "", " ", "N/A", "null"]: return 0
            return int(float(val))
        except: return 0

    # --- MASTER CLOUD WRITE HELPER ---
    def _write_to_db(self, table_name, data_list):
        """Helper to ensure every row has perfectly matching schema keys AND STRICT DATA TYPES before writing to DB."""
        if not data_list: return True
        schema = db_core.SCHEMAS.get(table_name, [])
        
        numeric_cols = {'Debit', 'Credit', 'Balance', 'Profit', 'Amount', 'Rate', 'Total Amount', 'Grand Total', 'Packing Charges', 'Freight Charges', 'Discount', 'Other Charges', 'Cost Price', 'Selling Price', 'Unit Rate', 'Line Amount'}
        int_cols = {'Ordered Qty', 'Delivered Qty', 'Pending Qty', 'Total Items', 'Total Quantity'}

        cleaned_list = []
        for data_dict in data_list:
            new_dict = {}
            for col in schema:
                val = data_dict.get(col)
                if col in numeric_cols:
                    new_dict[col] = self._safe_float(val)
                elif col in int_cols:
                    new_dict[col] = self._safe_int(val)
                else:
                    new_dict[col] = "" if val is None else str(val).strip()
            cleaned_list.append(new_dict)
            
        return db_core.write_table(table_name, cleaned_list)

    # --- AUTH ---
    def login(self, username="", password=""):
        try:
            users = db_core.read_table('UserMaster')
            for user in users:
                if str(user.get('Username')) == str(username) and str(user.get('Password')) == str(password):
                    if str(user.get('Status')).strip().title() != 'Active': 
                        return {"success": False, "error": "Account is inactive."}
                    user['Last Login'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._write_to_db('UserMaster', [user]) 
                    safe_user = dict(user)
                    safe_user['Password'] = "" 
                    return self._sanitize_data({"success": True, "user": safe_user})
            return {"success": False, "error": "Invalid username or password."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_profit_password(self, pwd=""):
        try:
            settings = db_core.read_table('Settings')
            actual = next((s.get('Setting Value') for s in settings if s.get('Setting Name') == 'Profit Password'), '')
            hashed_input = hashlib.sha256(str(pwd).encode('utf-8')).hexdigest()
            return {"success": hashed_input == actual}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- DASHBOARD & NOTIFICATIONS ---
    def get_dashboard_stats(self, role="", user_id=""):
        try:
            role_clean = str(role).strip().title()
            users = db_core.read_table('UserMaster')
            orders = db_core.read_table('OrderHeader')
            payments = db_core.read_table('PaymentMaster')
            ledger = db_core.read_table('LedgerMaster')
            
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            if role_clean == 'Customer':
                c_orders = [o for o in orders if str(o.get('Customer ID')) == str(user_id)]
                c_orders.sort(key=lambda x: str(x.get('Order ID', '')), reverse=True)
                
                c_ledger = [l for l in ledger if str(l.get('Customer ID')) == str(user_id)]
                c_ledger.sort(key=lambda x: (str(x.get('Date','')), str(x.get('Created Time', '')), str(x.get('Ledger ID', ''))))
                bal = self._safe_float(c_ledger[-1].get('Balance')) if c_ledger else 0.0

                pend_count = sum(1 for o in c_orders if o.get('Status') == 'Pending')
                part_count = sum(1 for o in c_orders if o.get('Status') == 'Partial')
                comp_count = sum(1 for o in c_orders if o.get('Status') == 'Completed')
                
                return self._sanitize_data({
                    "success": True,
                    "outstanding": bal,
                    "pending_orders": pend_count,
                    "partial_orders": part_count,
                    "completed_orders": comp_count,
                    "recent_orders": c_orders[:5]
                })
            else:
                total_cust = sum(1 for u in users if str(u.get('Role')).strip().title() == 'Customer')
                pending_orders = sum(1 for o in orders if o.get('Status') in ['Pending', 'Partial'])
                t_sales = sum(self._safe_float(o.get('Grand Total')) for o in orders if str(o.get('Order Date')) == today)
                
                # BUG FIX: Dashboard par Total Outstanding ab directly Ledger se calculate hoga
                # Purana shortcut (completed_sales - total_payments) manual entries aur adjustments ko ignore kar raha tha
                total_debit = sum(self._safe_float(l.get('Debit')) for l in ledger)
                total_credit = sum(self._safe_float(l.get('Credit')) for l in ledger)
                total_out = total_debit - total_credit

                notifications = db_core.read_table('AdminNotifications')
                notifications.sort(key=lambda x: str(x.get('Notif ID', '')), reverse=True)
                recent_notifications = notifications[:10]
                
                return self._sanitize_data({
                    "success": True,
                    "customers": total_cust,
                    "pending_orders": pending_orders,
                    "today_sales": t_sales,
                    "outstanding": total_out,
                    "notifications": recent_notifications
                })
        except Exception as e: return {"success": False, "error": str(e)}

    def mark_notifications_read(self):
        try:
            notifications = db_core.read_table('AdminNotifications')
            for n in notifications: n['Is Read'] = 'Yes'
            self._write_to_db('AdminNotifications', notifications)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- GLOBALS & MASTERS ---
    def get_active_verticals(self):
        try:
            verts = db_core.read_table('VerticalMaster')
            raw_list = sorted(list(set(str(v.get('Vertical Name', '')).strip() for v in verts if str(v.get('Status', '')).strip().lower() == 'active' and str(v.get('Vertical Name', '')).strip())))
            return self._sanitize_data(raw_list)
        except: return []

    def get_active_customers(self): 
        try:
            raw_list = [u for u in db_core.read_table('UserMaster') if str(u.get('Role', '')).strip().title() == 'Customer' and str(u.get('Status', '')).strip().title() == 'Active']
            return self._sanitize_data(raw_list)
        except: return []

    def get_users(self):
        try: return self._sanitize_data(db_core.read_table('UserMaster'))
        except: return []

    def get_products(self):
        try: return self._sanitize_data(db_core.read_table('ProductMaster'))
        except: return []

    def get_verticals(self):
        try: return self._sanitize_data(db_core.read_table('VerticalMaster'))
        except: return []

    def get_universals(self): 
        try:
            univs = db_core.read_table('UniversalMaster')
            materials = db_core.read_table('UniversalMaterials')
            for u in univs:
                u_mats = [m for m in materials if str(m.get('Universal Name')) == str(u.get('Universal Name'))]
                u['Materials'] = u_mats
            return self._sanitize_data(univs)
        except: return []

    # --- SAVE OPERATIONS ---
    def save_user(self, data=None):
        try:
            if data is None: return {"success": False, "error": "No payload"}
            users = db_core.read_table('UserMaster')
            uid = data.get('User ID')
            for u in users:
                if str(u.get('User ID')) != str(uid):
                    if str(u.get('Username')) == str(data.get('Username')): return {"success": False, "error": "Username exists."}
                    if str(u.get('Mobile Number')) == str(data.get('Mobile Number')) and str(data.get('Mobile Number')).strip() != "": return {"success": False, "error": "Mobile exists."}
            
            if not uid:
                data['User ID'] = self._generate_new_id(users, 'User ID', 'U', 3)
            else:
                for u in users:
                    if str(u.get('User ID')) == str(uid):
                        if not data.get('Password'): data['Password'] = u.get('Password')
                        break
                        
            if not self._write_to_db('UserMaster', [data]): return {"success": False, "error": "Database write failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def save_vertical(self, data=None):
        try:
            if data is None: return {"success": False, "error": "No payload"}
            verts = db_core.read_table('VerticalMaster')
            vid = data.get('Vertical ID')
            if not vid:
                data['Vertical ID'] = self._generate_new_id(verts, 'Vertical ID', 'V', 3)
                        
            if not self._write_to_db('VerticalMaster', [data]): return {"success": False, "error": "Database write failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def save_universal(self, data=None):
        try:
            if data is None: return {"success": False, "error": "No payload"}
            univs = db_core.read_table('UniversalMaster')
            
            orig = data.pop('_OriginalName', None)
            new_materials = data.pop('Materials', [])
            uname = data.get('Universal Name')
            
            if not orig or str(orig).strip() != str(uname).strip():
                if any(str(u.get('Universal Name')).lower() == str(uname).lower() for u in univs): 
                    return {"success": False, "error": "Universal Name already exists."}
            
            if orig:
                db_core.delete_records('UniversalMaterials', {'Universal Name': orig})
            if uname and str(uname) != str(orig):
                db_core.delete_records('UniversalMaterials', {'Universal Name': uname})

            for nm in new_materials:
                nm['Universal Name'] = uname
                
            s1 = self._write_to_db('UniversalMaster', [data]) 
            s2 = True
            if new_materials:
                s2 = self._write_to_db('UniversalMaterials', new_materials) 
            
            if not s1 or not s2: return {"success": False, "error": "Database write failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def save_product(self, data=None):
        try:
            if data is None: return {"success": False, "error": "No payload"}
            products = db_core.read_table('ProductMaster')
            pid = data.get('Product ID')
            if not pid:
                data['Product ID'] = self._generate_new_id(products, 'Product ID', 'P', 4)
            else:
                for p in products:
                    if str(p.get('Product ID')) == str(pid):
                        if 'Image Folder' not in data: data['Image Folder'] = p.get('Image Folder', '')
                        break
                        
            if not self._write_to_db('ProductMaster', [data]): return {"success": False, "error": "Database write failed."}
            return {"success": True, "productId": data['Product ID']}
        except Exception as e: return {"success": False, "error": str(e)}

    def save_profit_password(self, new_pwd=""):
        try:
            settings = db_core.read_table('Settings')
            hashed_pw = hashlib.sha256(str(new_pwd).encode('utf-8')).hexdigest()
            found = False
            for s in settings:
                if s.get('Setting Name') == 'Profit Password':
                    s['Setting Value'] = hashed_pw
                    found = True
                    break
            if not found:
                settings.append({'Setting Name': 'Profit Password', 'Setting Value': hashed_pw})
            
            if not self._write_to_db('Settings', settings): return {"success": False, "error": "Database write failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_user(self, user_id=""):
        try:
            if db_core.delete_records('UserMaster', {'User ID': user_id}): return {"success": True}
            return {"success": False, "error": "Safety guard active."}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_vertical(self, vid=""):
        try:
            if db_core.delete_records('VerticalMaster', {'Vertical ID': vid}): return {"success": True}
            return {"success": False, "error": "Safety guard active."}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_universal(self, name=""):
        try:
            s1 = db_core.delete_records('UniversalMaster', {'Universal Name': name})
            s2 = db_core.delete_records('UniversalMaterials', {'Universal Name': name})
            if s1 and s2: return {"success": True}
            return {"success": False, "error": "Safety guard active."}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_product(self, pid=""):
        try:
            if db_core.delete_records('ProductMaster', {'Product ID': pid}): return {"success": True}
            return {"success": False, "error": "Safety guard active."}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- CATALOG & ORDERING ---
    def get_order_entry_data(self, customer_id=""):
        try:
            user = next((u for u in db_core.read_table('UserMaster') if str(u.get('User ID')) == str(customer_id)), None)
            allowed_str = user.get('Allowed Verticals', '') if user else ''
            
            allowed_verts = [v.strip().lower() for v in str(allowed_str).split(',') if v.strip()] if allowed_str else []
            is_all = not allowed_verts or 'all' in allowed_verts

            products = [p for p in db_core.read_table('ProductMaster') if str(p.get('Status')).strip().title() == 'Active']
            if not is_all:
                products = [p for p in products if str(p.get('Vertical', '')).strip().lower() in allowed_verts]

            rates = [r for r in db_core.read_table('ProductRateMapping') if str(r.get('Customer ID')) == str(customer_id)]
            universals = db_core.read_table('UniversalMaster')
            materials_db = db_core.read_table('UniversalMaterials')
            
            mat_map = {}
            for m in materials_db:
                uname = str(m.get('Universal Name', '')).strip().lower()
                if uname not in mat_map: mat_map[uname] = []
                mat_map[uname].append(m)
            
            order_products = []
            pids = [p['Product ID'] for p in products]
            imgsRes = self.get_product_images_bulk(pids)

            for p in products:
                uni_name = p.get('Universal Name')
                uni_name_lower = str(uni_name).strip().lower()
                
                override_val_raw = str(p.get('Cost Price Override', '')).strip()
                overrides = {}
                if override_val_raw:
                    if override_val_raw.startswith('{'):
                        try: overrides = json.loads(override_val_raw)
                        except: pass
                    else:
                        try: overrides = {'LEGACY_ALL': self._safe_float(override_val_raw)}
                        except: pass
                
                p_mats = mat_map.get(uni_name_lower, [])
                if not p_mats:
                    cost_price = next((self._safe_float(u.get('Cost Price')) for u in universals if str(u.get('Universal Name')).strip().lower() == uni_name_lower), 0.0)
                    p_mats = [{'Material': 'Clear', 'Selling Price': 0.0, 'Cost Price': cost_price, 'Is Default': 'Yes'}]

                processed_mats = []
                for m in p_mats:
                    mat_name = str(m.get('Material', 'Clear')).strip()
                    mat_name_lower = mat_name.lower()
                    
                    default_sp = self._safe_float(m.get('Selling Price'))
                    base_cp = self._safe_float(m.get('Cost Price'))
                    
                    final_cp = base_cp
                    if overrides.get(mat_name) not in [None, ""]:
                        try: final_cp = self._safe_float(overrides[mat_name])
                        except: pass
                    elif 'LEGACY_ALL' in overrides:
                        final_cp = self._safe_float(overrides.get('LEGACY_ALL'))
                    
                    mapped_rate_str = ""
                    for r in rates:
                        r_uni = str(r.get('Universal Name', '')).strip().lower()
                        r_mat = str(r.get('Material', '')).strip().lower()
                        if not r_mat: r_mat = 'clear'
                            
                        if r_uni == uni_name_lower and r_mat == mat_name_lower:
                            mapped_rate_str = r.get('Rate', "")
                            break
                            
                    final_sp = self._safe_float(mapped_rate_str) if str(mapped_rate_str).strip() != "" else default_sp
                    
                    processed_mats.append({
                        'Material': mat_name,
                        'Selling Price': final_sp,
                        'Cost Price': final_cp,
                        'Is Default': m.get('Is Default', 'No')
                    })
                    
                if processed_mats and not any(m['Is Default'] == 'Yes' for m in processed_mats):
                    processed_mats[0]['Is Default'] = 'Yes'

                b64Img = (imgsRes.get('success') and imgsRes.get('images', {}).get(p['Product ID'])) or ''

                order_products.append({
                    "Product ID": p.get('Product ID'), "Product Title": p.get('Product Title'),
                    "Company": p.get('Company'), "Universal Name": uni_name, "Trending": p.get('Trending'),
                    "Manufacturing Folder Path": p.get('Manufacturing Folder Path', ''),
                    "Vertical": p.get('Vertical', ''),
                    "Image": b64Img,
                    "Materials": processed_mats
                })
            return self._sanitize_data({"success": True, "products": order_products})
        except Exception as e: return {"success": False, "error": str(e)}

    def submit_order(self, payload=None):
        try:
            if payload is None: return {"success": False, "error": "No payload"}
            headers = db_core.read_table('OrderHeader')
            users = db_core.read_table('UserMaster')

            new_order_id = self._generate_new_id(headers, 'Order ID', 'ORD-', 5)
            now = datetime.datetime.now()
            order_date = now.strftime("%Y-%m-%d")
            created_time = now.strftime("%H:%M:%S")

            cust_name = ""
            for u in users:
                if str(u.get('User ID')) == str(payload.get('customerId')):
                    cust_name = str(u.get('User Name'))
                    u['Last Order Date'] = order_date
                    self._write_to_db('UserMaster', [u])
                    break

            total_items = len(payload.get('items', []))
            total_qty = sum(self._safe_int(item.get('orderedQty')) for item in payload.get('items', []))
            total_amount = sum(self._safe_float(item.get('rate')) * self._safe_int(item.get('orderedQty')) for item in payload.get('items', []))

            h_data = {
                'Order ID': new_order_id, 'Order Date': order_date, 'Customer ID': payload.get('customerId'),
                'Customer Name': cust_name, 'Total Items': total_items, 'Total Quantity': total_qty,
                'Total Amount': total_amount, 'Packing Charges': 0.0, 'Freight Charges': 0.0,
                'Discount': 0.0, 'Other Charges': 0.0, 'Misc Description': '',
                'Grand Total': total_amount, 'Special Message': payload.get('specialMessage', ''),
                'Status': 'Pending', 'Created By': payload.get('createdBy', ''), 'Created Time': created_time
            }

            d_data_list = []
            for idx, item in enumerate(payload.get('items', [])):
                ordered_qty = self._safe_int(item.get('orderedQty'))
                rate = self._safe_float(item.get('rate'))
                cost_p = self._safe_float(item.get('costPrice'))
                
                d_data_list.append({
                    'Order Detail ID': f"{new_order_id}-{idx+1:03d}", 'Order ID': new_order_id,
                    'Product ID': item.get('productId'), 'Product Title': item.get('productTitle'),
                    'Universal Name': item.get('universalName'), 'Material': item.get('material', 'Clear'),
                    'Company': item.get('company'),
                    'Ordered Qty': ordered_qty, 'Delivered Qty': 0, 'Pending Qty': ordered_qty,
                    'Unit Rate': rate, 'Cost Price': cost_p,
                    'Line Amount': ordered_qty * rate, 'Status': 'Pending',
                    'Prepared By': '', 'Prepared Time': ''
                })

            s1 = self._write_to_db('OrderHeader', [h_data])
            s2 = self._write_to_db('OrderDetails', d_data_list)
            if not s1 or not s2: return {"success": False, "error": "Database write failed."}
            return {"success": True, "orderId": new_order_id}
        except Exception as e: return {"success": False, "error": str(e)}

    def get_orders_history(self, user_role="", customer_id=""):
        try:
            headers = db_core.read_table('OrderHeader')
            if str(user_role).strip().title() == 'Customer': 
                headers = [h for h in headers if str(h.get('Customer ID')) == str(customer_id)]
            headers.sort(key=lambda x: str(x.get('Order ID', '')), reverse=True)
            return self._sanitize_data({"success": True, "orders": headers})
        except Exception as e: return {"success": False, "error": str(e)}

    def get_order_details(self, order_id=""):
        try:
            header = next((h for h in db_core.read_table('OrderHeader') if str(h.get('Order ID')) == str(order_id)), None)
            items = [d for d in db_core.read_table('OrderDetails') if str(d.get('Order ID')) == str(order_id)]
            if not header: return {"success": False, "error": "Order not found."}
            return self._sanitize_data({"success": True, "header": header, "items": items})
        except Exception as e: return {"success": False, "error": str(e)}

    def process_order(self, payload=None):
        try:
            if payload is None: return {"success": False, "error": "No payload"}
            order_id = payload.get('orderId')
            staff_name = payload.get('staffName', 'System')
            staff_id = payload.get('staffId', '') 
            prep_str = f"{staff_name} ({staff_id})" if staff_id else staff_name
            
            headers = db_core.read_table('OrderHeader')
            details = db_core.read_table('OrderDetails')

            total_ordered = 0
            total_delivered = 0
            new_base_amount = 0.0
            
            d_updates = []
            
            for update_item in payload.get('items', []):
                detail_id = update_item.get('detailId')
                delivered_qty = self._safe_int(update_item.get('deliveredQty'))
                is_prepared = update_item.get('isPrepared') 
                
                for d in details:
                    if str(d.get('Order Detail ID')) == str(detail_id):
                        ordered_qty = self._safe_int(d.get('Ordered Qty'))
                        rate = self._safe_float(d.get('Unit Rate'))
                        
                        d['Delivered Qty'] = delivered_qty
                        d['Pending Qty'] = ordered_qty - delivered_qty
                        d['Line Amount'] = delivered_qty * rate
                        
                        if self._safe_int(d.get('Pending Qty')) <= 0: d['Status'] = 'Completed'
                        elif delivered_qty > 0: d['Status'] = 'Partial'
                        else: d['Status'] = 'Pending'

                        if is_prepared is not None:
                            if is_prepared:
                                d['Prepared By'] = prep_str
                                d['Prepared Time'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                notifications = db_core.read_table('AdminNotifications')
                                msg = f"{staff_name} packed {delivered_qty} of {d.get('Product Title')} for Order {order_id}"
                                recent = [n for n in notifications if str(n.get('Message')) == msg]
                                if not recent:
                                    notif_data = {
                                        'Notif ID': f"N{len(notifications)+1:06d}",
                                        'Date Time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        'Message': msg,
                                        'Is Read': 'No'
                                    }
                                    self._write_to_db('AdminNotifications', [notif_data])
                            else:
                                d['Prepared By'] = ""
                                d['Prepared Time'] = ""
                        
                        total_ordered += ordered_qty
                        total_delivered += delivered_qty
                        new_base_amount += d.get('Line Amount')
                        d_updates.append(d)
                        break

            auto_status = 'Pending'
            if total_delivered > 0:
                if total_delivered >= total_ordered: auto_status = 'Completed'
                else: auto_status = 'Partial'

            customer_id = ""
            customer_name = ""
            date_str = ""
            grand_total = 0.0

            h_update = None
            for h in headers:
                if str(h.get('Order ID')) == str(order_id):
                    h['Status'] = auto_status
                    customer_id = h.get('Customer ID')
                    customer_name = h.get('Customer Name')
                    date_str = h.get('Order Date')
                    
                    if 'packing' in payload: h['Packing Charges'] = self._safe_float(payload.get('packing'))
                    if 'freight' in payload: h['Freight Charges'] = self._safe_float(payload.get('freight'))
                    if 'discount' in payload: h['Discount'] = self._safe_float(payload.get('discount'))
                    if 'other' in payload: h['Other Charges'] = self._safe_float(payload.get('other'))
                    if 'miscDesc' in payload: h['Misc Description'] = str(payload.get('miscDesc', ''))
                    
                    p_charge = self._safe_float(h.get('Packing Charges'))
                    f_charge = self._safe_float(h.get('Freight Charges'))
                    d_charge = self._safe_float(h.get('Discount'))
                    o_charge = self._safe_float(h.get('Other Charges'))

                    h['Total Amount'] = new_base_amount
                    h['Grand Total'] = new_base_amount + p_charge + f_charge + o_charge - d_charge
                    grand_total = self._safe_float(h.get('Grand Total'))
                    h_update = h
                    break

            if h_update: self._write_to_db('OrderHeader', [h_update])
            if d_updates: self._write_to_db('OrderDetails', d_updates)

            if auto_status == 'Completed' and customer_id:
                ledger = db_core.read_table('LedgerMaster')
                existing_idx = next((i for i, l in enumerate(ledger) if str(l.get('Reference ID')) == str(order_id) and str(l.get('Reference Type')) == 'Order Delivery'), None)
                if existing_idx is not None: 
                    ledger[existing_idx]['Debit'] = grand_total
                    self._write_to_db('LedgerMaster', [ledger[existing_idx]])
                else:
                    new_lid = self._generate_new_id(ledger, 'Ledger ID', 'L', 5)
                    l_data = {
                        'Ledger ID': new_lid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': customer_name,
                        'Order ID': order_id, 'Transaction Type': 'Order Delivery', 'Profit': 0,
                        'Reference Type': 'Order Delivery', 'Reference ID': order_id, 'Debit': grand_total, 'Credit': 0,
                        'Balance': 0, 'Remarks': 'Order Processed', 'Created By': 'System', 'Created Time': datetime.datetime.now().strftime("%H:%M:%S")
                    }
                    self._write_to_db('LedgerMaster', [l_data])
                db_core.rebuild_customer_ledger(customer_id)

            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_order(self, order_id=""):
        try:
            h = next((h for h in db_core.read_table('OrderHeader') if str(h.get('Order ID')) == str(order_id)), None)
            if h:
                c_id = h.get('Customer ID')
                s1 = db_core.delete_records('OrderHeader', {'Order ID': order_id})
                s2 = db_core.delete_records('OrderDetails', {'Order ID': order_id})
                db_core.delete_records('LedgerMaster', {'Reference ID': order_id, 'Reference Type': 'Order Delivery'})
                db_core.rebuild_customer_ledger(c_id)
                if not s1 or not s2: return {"success": False, "error": "Database delete failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- RATES MAPPING ---
    def get_rate_mapping_init(self, role="", user_id=""):
        try:
            role_clean = str(role).strip().lower()
            user_id_clean = str(user_id).strip()
            
            users = [u for u in db_core.read_table('UserMaster') if str(u.get('Role', '')).strip().lower() == 'customer' and str(u.get('Status', '')).strip().lower() == 'active']
            
            if role_clean and role_clean != 'admin':
                users = [u for u in users if str(u.get('User ID')).strip() == user_id_clean]
                
            return self._sanitize_data({"success": True, "customers": users})
        except Exception as e: return {"success": False, "error": str(e)}

    def get_customer_rates(self, customer_id="", role="", logged_in_user_id=""):
        try:
            role_clean = str(role).strip().lower()
            req_cust_id = str(customer_id).strip()
            logged_id = str(logged_in_user_id).strip()
            
            if role_clean and role_clean != 'admin' and req_cust_id != logged_id:
                return {"success": False, "error": "Unauthorized access."}
                
            univs = [u for u in db_core.read_table('UniversalMaster') if str(u.get('Status', '')).strip().title() == 'Active']
            materials_db = db_core.read_table('UniversalMaterials')
            rates = [r for r in db_core.read_table('ProductRateMapping') if str(r.get('Customer ID')).strip() == req_cust_id]
            
            result = []
            for u in univs:
                uname = u.get('Universal Name')
                uname_lower = str(uname).strip().lower()
                
                u_mats = [m for m in materials_db if str(m.get('Universal Name')).strip().lower() == uname_lower]
                if not u_mats:
                    u_mats = [{'Material': 'Clear', 'Selling Price': 0.0}]
                    
                for m in u_mats:
                    mat_name = str(m.get('Material', 'Clear')).strip()
                    mat_name_lower = mat_name.lower()
                    default_rate = self._safe_float(m.get('Selling Price'))
                    
                    mapped_rate = ""
                    for r in rates:
                        r_uni = str(r.get('Universal Name', '')).strip().lower()
                        r_mat = str(r.get('Material', '')).strip().lower()
                        if not r_mat: r_mat = 'clear'
                        
                        if r_uni == uname_lower and r_mat == mat_name_lower:
                            mapped_rate = r.get('Rate', "")
                            break
                    
                    result.append({
                        "Universal Name": uname, 
                        "Material": mat_name,
                        "Default Rate": default_rate, 
                        "Rate": mapped_rate
                    })
            return self._sanitize_data({"success": True, "rates": result})
        except Exception as e: return {"success": False, "error": str(e)}

    def save_rate(self, cust_id="", uni_name="", material="", rate="", role="", logged_in_user_id=""):
        try:
            role_clean = str(role).strip().lower()
            if role_clean and role_clean != 'admin':
                return {"success": False, "error": "Unauthorized."}
                
            rates = db_core.read_table('ProductRateMapping')
            if rates is None: rates = []

            uni_name_lower = str(uni_name).strip().lower()
            mat_name_lower = str(material).strip().lower()
            
            for r in rates:
                r_uni = str(r.get('Universal Name', '')).strip().lower()
                r_mat = str(r.get('Material', '')).strip().lower()
                if not r_mat: r_mat = 'clear'
                
                if str(r.get('Customer ID')).strip() == str(cust_id).strip() and r_uni == uni_name_lower and r_mat == mat_name_lower:
                    db_core.delete_records('ProductRateMapping', {
                        'Customer ID': r.get('Customer ID'),
                        'Universal Name': r.get('Universal Name'),
                        'Material': r.get('Material')
                    })
                    break
                    
            if str(rate).strip() != "":
                r_data = {
                    'Customer ID': cust_id, 
                    'Universal Name': uni_name, 
                    'Material': material, 
                    'Rate': rate
                }
                if not self._write_to_db('ProductRateMapping', [r_data]): 
                    return {"success": False, "error": "Database write failed."}
                
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- FINANCIALS ---
    def add_ledger_entry(self, payload=None):
        try:
            if payload is None: return {"success": False, "error": "No payload"}
            customer_id = payload.get('customerId')
            entry_type = payload.get('entryType')
            amount = self._safe_float(payload.get('amount'))
            remarks = payload.get('remarks')
            date_str = payload.get('date')

            users = db_core.read_table('UserMaster')
            cust_name = next((u.get('User Name') for u in users if str(u.get('User ID')) == str(customer_id)), "")

            ledger = db_core.read_table('LedgerMaster')
            new_lid = self._generate_new_id(ledger, 'Ledger ID', 'L', 5)
            created_time = datetime.datetime.now().strftime("%H:%M:%S")

            s1 = True
            s2 = True

            if entry_type == 'Payment Received':
                payments = db_core.read_table('PaymentMaster')
                pid = self._generate_new_id(payments, 'Payment ID', 'PAY-', 5)
                
                # Payment Master array
                s1 = self._write_to_db('PaymentMaster', [{
                    'Payment ID': pid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': cust_name,
                    'Amount': amount, 'Payment Mode': 'Other', 'Transaction Number': '', 'Remarks': remarks,
                    'Created By': 'Manual Entry', 'Created Time': created_time
                }])

                # Ledger Master array
                s2 = self._write_to_db('LedgerMaster', [{
                    'Ledger ID': new_lid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': cust_name,
                    'Order ID': '', 'Transaction Type': 'Payment Receipt', 'Profit': 0,
                    'Reference Type': 'Payment Receipt', 'Reference ID': pid, 'Debit': 0, 'Credit': amount,
                    'Balance': 0, 'Remarks': remarks, 'Created By': 'Manual Entry', 'Created Time': created_time
                }])

            elif entry_type == 'Miscellaneous Sale':
                s2 = self._write_to_db('LedgerMaster', [{
                    'Ledger ID': new_lid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': cust_name,
                    'Order ID': '', 'Transaction Type': 'Misc Sale', 'Profit': 0,
                    'Reference Type': 'Misc Sale', 'Reference ID': 'MISC', 'Debit': amount, 'Credit': 0,
                    'Balance': 0, 'Remarks': remarks, 'Created By': 'Manual Entry', 'Created Time': created_time
                }])

            elif entry_type == 'Adjustment':
                s2 = self._write_to_db('LedgerMaster', [{
                    'Ledger ID': new_lid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': cust_name,
                    'Order ID': '', 'Transaction Type': 'Adjustment', 'Profit': 0,
                    'Reference Type': 'Adjustment', 'Reference ID': 'ADJ', 'Debit': 0, 'Credit': amount,
                    'Balance': 0, 'Remarks': remarks, 'Created By': 'Manual Entry', 'Created Time': created_time
                }])
                
            if not s1 or not s2:
                return {"success": False, "error": "Database write failed during manual entry."}

            db_core.rebuild_customer_ledger(customer_id)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def get_payments(self):
        try:
            payments = db_core.read_table('PaymentMaster')
            payments.sort(key=lambda x: str(x.get('Payment ID', '')), reverse=True)
            return self._sanitize_data({"success": True, "payments": payments})
        except Exception as e: return {"success": False, "error": str(e)}

    def save_payment(self, payload=None):
        try:
            if payload is None: return {"success": False, "error": "No payload"}
            payments = db_core.read_table('PaymentMaster')
            users = db_core.read_table('UserMaster')
            
            pid = payload.get('Payment ID')
            customer_id = payload.get('Customer ID')
            customer_name = next((u.get('User Name') for u in users if str(u.get('User ID')) == str(customer_id)), "")
            amount = self._safe_float(payload.get('Amount'))
            date_str = payload.get('Date')

            if not pid:
                pid = self._generate_new_id(payments, 'Payment ID', 'PAY-', 5)
                payload['Payment ID'] = pid
                payload['Customer Name'] = customer_name
                payload['Created Time'] = datetime.datetime.now().strftime("%H:%M:%S")
            else:
                for i, p in enumerate(payments):
                    if str(p.get('Payment ID')) == str(pid):
                        payload['Customer Name'] = customer_name
                        payload['Created Time'] = p.get('Created Time', datetime.datetime.now().strftime("%H:%M:%S"))
                        break
            
            s1 = self._write_to_db('PaymentMaster', [payload])

            ledger = db_core.read_table('LedgerMaster')
            existing_idx = next((i for i, l in enumerate(ledger) if str(l.get('Reference ID')) == str(pid) and str(l.get('Reference Type')) == 'Payment Receipt'), None)
            if existing_idx is not None:
                ledger[existing_idx]['Credit'] = amount
                ledger[existing_idx]['Date'] = date_str
                s2 = self._write_to_db('LedgerMaster', [ledger[existing_idx]])
            else:
                new_lid = self._generate_new_id(ledger, 'Ledger ID', 'L', 5)
                s2 = self._write_to_db('LedgerMaster', [{
                    'Ledger ID': new_lid, 'Date': date_str, 'Customer ID': customer_id, 'Customer Name': customer_name,
                    'Order ID': '', 'Transaction Type': 'Payment Receipt', 'Profit': 0,
                    'Reference Type': 'Payment Receipt', 'Reference ID': pid, 'Debit': 0, 'Credit': amount,
                    'Balance': 0, 'Remarks': payload.get('Remarks', ''), 'Created By': payload.get('Created By', ''),
                    'Created Time': payload.get('Created Time', '')
                }])
                
            db_core.rebuild_customer_ledger(customer_id)
            if not s1 or not s2: return {"success": False, "error": "Database write failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_payment(self, pay_id=""):
        try:
            p = next((p for p in db_core.read_table('PaymentMaster') if str(p.get('Payment ID')) == str(pay_id)), None)
            if p:
                c_id = p.get('Customer ID')
                s1 = db_core.delete_records('PaymentMaster', {'Payment ID': pay_id})
                db_core.delete_records('LedgerMaster', {'Reference ID': pay_id, 'Reference Type': 'Payment Receipt'})
                db_core.rebuild_customer_ledger(c_id)
                if not s1: return {"success": False, "error": "Database delete failed."}
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def get_accounts_summary(self):
        try:
            users = [u for u in db_core.read_table('UserMaster') if str(u.get('Role')).strip().title() == 'Customer']
            ledger = db_core.read_table('LedgerMaster')
            accs = []
            for u in users:
                cid = str(u.get('User ID', '')).strip().lower()
                c_ledg = [l for l in ledger if str(l.get('Customer ID', '')).strip().lower() == cid]
                
                tot_sales = sum(self._safe_float(l.get('Debit')) for l in c_ledg)
                tot_pay = sum(self._safe_float(l.get('Credit')) for l in c_ledg)
                c_ledg.sort(key=lambda x: (str(x.get('Date','')), str(x.get('Created Time', '')), str(x.get('Ledger ID', ''))))
                bal = self._safe_float(c_ledg[-1].get('Balance')) if c_ledg else 0.0
                accs.append({"Customer ID": u.get('User ID'), "Customer Name": u.get('User Name'), "Total Sales": tot_sales, "Total Payments": tot_pay, "Balance": bal})
            return self._sanitize_data({"success": True, "accounts": accs})
        except Exception as e: return {"success": False, "error": str(e)}

    def get_customer_statement(self, customer_id=""):
        try:
            users = db_core.read_table('UserMaster')
            ledger = db_core.read_table('LedgerMaster')
            
            clean_customer_id = str(customer_id).strip().lower()
            
            u = next((x for x in users if str(x.get('User ID', '')).strip().lower() == clean_customer_id), None)
            if not u: return {"success": False, "error": "Customer not found"}
            
            c_ledg = [l for l in ledger if str(l.get('Customer ID', '')).strip().lower() == clean_customer_id]
            c_ledg.sort(key=lambda x: (str(x.get('Date','')), str(x.get('Created Time', '')), str(x.get('Ledger ID', ''))))
            
            tot_sales = sum(self._safe_float(l.get('Debit')) for l in c_ledg)
            tot_pay = sum(self._safe_float(l.get('Credit')) for l in c_ledg)
            bal = self._safe_float(c_ledg[-1].get('Balance')) if c_ledg else 0.0
            
            return self._sanitize_data({"success": True, "customer": {"Customer Name": u.get('User Name'), "Total Sales": tot_sales, "Total Payments": tot_pay, "Balance": bal}, "ledger": c_ledg})
        except Exception as e: return {"success": False, "error": str(e)}

    def get_profit_data(self):
        try:
            orders = db_core.read_table('OrderHeader')
            details = db_core.read_table('OrderDetails')
            univs = db_core.read_table('UniversalMaster')
            vert_map = {str(u.get('Universal Name')).lower(): str(u.get('Vertical', '')) for u in univs}
            
            data = []
            for d in details:
                del_qty = self._safe_int(d.get('Delivered Qty'))
                if del_qty <= 0: continue
                
                oid = str(d.get('Order ID', ''))
                h = next((o for o in orders if str(o.get('Order ID')) == oid), None)
                if not h: continue
                
                unit_rate = self._safe_float(d.get('Unit Rate'))
                cost_price = self._safe_float(d.get('Cost Price'))
                sales = unit_rate * del_qty
                cost = cost_price * del_qty
                profit = sales - cost
                
                uname = str(d.get('Universal Name', ''))
                order_date = str(h.get('Order Date', ''))
                
                data.append({
                    "Order ID": oid,
                    "Order Date": order_date,
                    "Order Month": order_date[:7] if order_date else '',
                    "Order Year": order_date[:4] if order_date else '',
                    "Customer Name": h.get('Customer Name'),
                    "Product Title": d.get('Product Title'),
                    "Company": d.get('Company'),
                    "Universal Name": uname,
                    "Vertical": vert_map.get(uname.lower(), ''),
                    "Delivered Qty": del_qty,
                    "Sales": sales,
                    "Cost": cost,
                    "Profit": profit
                })
            return self._sanitize_data({"success": True, "data": data})
        except Exception as e: return {"success": False, "error": str(e)}

    # --- FILE & IMAGES ---
    def open_manufacturing_file(self, file_path=""):
        try:
            if not file_path or str(file_path).strip() in ['N/A', '']: return {"success": False, "error": "No file path defined."}
            return self._sanitize_data({"success": True, "path": file_path, "message": "Cloud mode: Use frontend to download/open this path."})
        except Exception as e: return {"success": False, "error": str(e)}

    def check_manufacturing_file(self, file_path=""):
        try:
            if not file_path or str(file_path).strip() in ['N/A', '']: return False
            return True 
        except: return False

    def get_product_images(self, product_id=""):
        try:
            folder = f"products/{product_id}"
            files = self.storage.list_files(folder)
            images = [{"filename": f, "data": self.storage.get_file_b64(folder, f)} for f in files]
            return self._sanitize_data({"success": True, "images": images})
        except Exception as e: return {"success": False, "error": str(e)}

    def get_product_images_bulk(self, product_ids=None):
        try:
            if product_ids is None: product_ids = []
            res = {}
            for pid in set(product_ids):
                folder = f"products/{pid}"
                files = self.storage.list_files(folder)
                if files:
                    default_file = next((f for f in files if '⭐' in f), files[0])
                    res[pid] = self.storage.get_file_b64(folder, default_file)
                else:
                    res[pid] = "" 
            return self._sanitize_data({"success": True, "images": res})
        except Exception as e: return {"success": False, "error": str(e)}

    def upload_product_image(self, product_id="", filename="", b64_data=""):
        try:
            folder = f"products/{product_id}"
            folder_path = self.storage.save(folder, filename, b64_data)
            products = db_core.read_table('ProductMaster')
            for p in products:
                if str(p.get('Product ID')) == str(product_id):
                    p['Image Folder'] = folder_path
                    self._write_to_db('ProductMaster', [p])
                    break
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def delete_product_image(self, product_id="", filename=""):
        try:
            folder = f"products/{product_id}"
            self.storage.delete(folder, filename)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def backup_data(self):
        try:
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_data_dict = {}
            for table_name in db_core.SCHEMAS.keys():
                backup_data_dict[table_name] = db_core.read_table(table_name)
                
            backup_folder = Path('backups')
            backup_folder.mkdir(exist_ok=True)
            file_path = backup_folder / f"CloudBackup_{now}.json"
            
            with open(file_path, 'w') as f:
                json.dump(backup_data_dict, f)
                
            self._write_to_db('BackupLog', [{'Backup Date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'Backup File': f"{file_path.name}", 'Created By': 'Admin'}])
            return self._sanitize_data({"success": True, "path": str(file_path)})
        except Exception as e: return {"success": False, "error": str(e)}