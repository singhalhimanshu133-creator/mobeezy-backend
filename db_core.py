import os
import hashlib
import base64
from supabase import create_client, Client

# ==========================================
# 1. SUPABASE CONNECTION
# ==========================================
SUPABASE_URL = "https://eznlneklxmrtpnbryzwl.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bmxuZWtseG1ydHBuYnJ5endsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTUzNTY1NywiZXhwIjoyMTAxMTExNjU3fQ.8omKupTDpgdfgb9alMzLaP3Gsd1Hez4DRB2CIBzeLM0"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"⚠️ Supabase Init Error: {e}")
    supabase = None

# ==========================================
# 2. SCHEMA & DATA TYPES
# ==========================================
SCHEMAS = {
    'UserMaster': ['User ID', 'User Name', 'Mobile Number', 'Username', 'Password', 'Role', 'Show Rates', 'Allowed Verticals', 'Can View Profit', 'Can Add Ledger', 'Status', 'Last Login', 'Last Order Date', 'Remarks'],
    'VerticalMaster': ['Vertical ID', 'Vertical Name', 'Status'],
    'UniversalMaster': ['Universal Name', 'Vertical', 'Cost Price', 'Status', 'Remarks'],
    'UniversalMaterials': ['Universal Name', 'Material', 'Selling Price', 'Cost Price', 'Is Default'],
    'ProductMaster': ['Product ID', 'Company', 'Product Title', 'Universal Name', 'Vertical', 'Manufacturing Folder Path', 'Image Folder', 'Trending', 'Status', 'Cost Price Override', 'Remarks'],
    'ProductRateMapping': ['Customer ID', 'Universal Name', 'Material', 'Rate'],
    'OrderHeader': ['Order ID', 'Order Date', 'Customer ID', 'Customer Name', 'Total Items', 'Total Quantity', 'Total Amount', 'Packing Charges', 'Freight Charges', 'Discount', 'Other Charges', 'Misc Description', 'Grand Total', 'Special Message', 'Status', 'Created By', 'Created Time'],
    'OrderDetails': ['Order Detail ID', 'Order ID', 'Product ID', 'Product Title', 'Universal Name', 'Material', 'Company', 'Ordered Qty', 'Delivered Qty', 'Pending Qty', 'Unit Rate', 'Cost Price', 'Line Amount', 'Status', 'Prepared By', 'Prepared Time'],
    'LedgerMaster': ['Ledger ID', 'Date', 'Customer ID', 'Customer Name', 'Order ID', 'Transaction Type', 'Debit', 'Credit', 'Balance', 'Profit', 'Reference Type', 'Reference ID', 'Remarks', 'Created By', 'Created Time'],
    'PaymentMaster': ['Payment ID', 'Date', 'Customer ID', 'Customer Name', 'Amount', 'Payment Mode', 'Transaction Number', 'Remarks', 'Created By', 'Created Time'],
    'Settings': ['Setting Name', 'Setting Value'],
    'BackupLog': ['Backup Date', 'Backup File', 'Created By'],
    'AdminNotifications': ['Notif ID', 'Date Time', 'Message', 'Is Read']
}

# Strict Numeric Fields (Cloud Database ko rate/amount ke liye numbers chahiye)
NUMERIC_COLUMNS = {
    'Rate', 'Selling Price', 'Cost Price', 'Total Items', 'Total Quantity', 'Total Amount', 
    'Packing Charges', 'Freight Charges', 'Discount', 'Other Charges', 'Grand Total', 
    'Ordered Qty', 'Delivered Qty', 'Pending Qty', 'Unit Rate', 'Line Amount', 
    'Debit', 'Credit', 'Balance', 'Profit', 'Amount'
}

# ==========================================
# 3. CORE LOGIC (SAFE READ/WRITE & CLEANING)
# ==========================================
def _clean_row(table_name, row):
    """Surgical cleaning: Prevents Database write failures by casting correct data types."""
    clean_row = {}
    schema_cols = SCHEMAS.get(table_name, [])
    
    for key in schema_cols:
        val = row.get(key)
        
        # Numeric Sanitization
        if key in NUMERIC_COLUMNS:
            if val is None or str(val).strip() in ["", "None", "null", "N/A", " "]:
                clean_row[key] = None
            else:
                try: 
                    clean_row[key] = float(val)
                except: 
                    clean_row[key] = None
        # String Sanitization
        else:
            if val is None:
                clean_row[key] = ""
            else:
                clean_row[key] = str(val).strip()
                
    return clean_row

def read_table(table_name):
    """Reads table from Supabase and handles missing columns dynamically."""
    try:
        if not supabase: return []
        response = supabase.table(table_name).select("*").execute()
        data = response.data if response.data else []
        
        required_headers = SCHEMAS.get(table_name, [])
        formatted_data = []
        seen_rows = set()
        
        for row_dict in data:
            for req in required_headers:
                if req not in row_dict or row_dict[req] is None:
                    row_dict[req] = ""
            
            # Duplicate filter fingerprint
            fingerprint = tuple(str(row_dict.get(key, '')).strip().lower() for key in required_headers)
            if fingerprint not in seen_rows:
                seen_rows.add(fingerprint)
                formatted_data.append(row_dict)
                
        return formatted_data
    except Exception as e:
        print(f"Error reading {table_name}: {e}")
        return []

def write_table(table_name, data):
    """Safely writes or updates records using type-cleaned payloads."""
    if data is None:
        raise ValueError("write_table() received None")
    if len(data) == 0:
        print(f"WARNING: Refusing to overwrite {table_name} with empty data.")
        return False
        
    try:
        clean_data = [_clean_row(table_name, row) for row in data]
        supabase.table(table_name).upsert(clean_data).execute()
        return True
    except Exception as e:
        print(f"CRITICAL DB WRITE ERROR ({table_name}): {e}")
        return False

def delete_records(table_name, match_dict):
    """Deletes specific rows from Cloud DB using match criteria."""
    try:
        query = supabase.table(table_name).delete()
        for k, v in match_dict.items():
            query = query.eq(k, v)
        query.execute()
        return True
    except Exception as e:
        print(f"Delete Error: {e}")
        return False

# ==========================================
# 4. INITIALIZATION & LEDGER LOGIC
# ==========================================
def init_db():
    """Initializes default Admin, Profit Password, and Vertical Seeding."""
    try:
        users = read_table('UserMaster')
        if not any(u.get('Username') == 'admin' for u in users):
            admin_user = {
                'User ID': 'U001', 'User Name': 'Super Admin', 'Mobile Number': '0000000000', 
                'Username': 'admin', 'Password': 'password', 'Role': 'Admin', 
                'Show Rates': 'Yes', 'Allowed Verticals': 'All', 'Can View Profit': 'Yes', 'Can Add Ledger': 'Yes', 'Status': 'Active', 
                'Last Login': '', 'Last Order Date': '', 'Remarks': 'System Generated'
            }
            users.append(admin_user)
            write_table('UserMaster', users)

        settings = read_table('Settings')
        if not any(s.get('Setting Name') == 'Profit Password' for s in settings):
            hashed_pw = hashlib.sha256(b"admin123").hexdigest()
            settings.append({'Setting Name': 'Profit Password', 'Setting Value': hashed_pw})
            write_table('Settings', settings)

        verts = read_table('VerticalMaster')
        if not verts:
            prods = read_table('ProductMaster')
            migrated_verts = []
            existing_verticals = set()
            for p in prods:
                v_val = str(p.get('Vertical', '')).strip()
                if v_val: existing_verticals.add(v_val)
            
            existing_verticals = sorted(list(existing_verticals))
            if existing_verticals:
                for i, v_name in enumerate(existing_verticals, start=1):
                    migrated_verts.append({'Vertical ID': f"V{i:03d}", 'Vertical Name': v_name, 'Status': 'Active'})
            else:
                migrated_verts = [
                    {'Vertical ID': 'V001', 'Vertical Name': 'Mobile', 'Status': 'Active'},
                    {'Vertical ID': 'V002', 'Vertical Name': 'Car', 'Status': 'Active'},
                    {'Vertical ID': 'V003', 'Vertical Name': 'Bike', 'Status': 'Active'},
                    {'Vertical ID': 'V004', 'Vertical Name': 'Rings', 'Status': 'Active'},
                    {'Vertical ID': 'V005', 'Vertical Name': 'Tablet', 'Status': 'Active'},
                    {'Vertical ID': 'V006', 'Vertical Name': 'Watch', 'Status': 'Active'}
                ]
            write_table('VerticalMaster', migrated_verts)
    except Exception as e:
        print(f"Init DB Error: {e}")

def rebuild_customer_ledger(customer_id):
    """Accurate running balance recalculation with strict cleaning."""
    try:
        def _safe_float(val):
            try:
                if val in [None, "", " ", "N/A", "null"]: return 0.0
                return float(val)
            except:
                return 0.0

        all_data = read_table('LedgerMaster')
        cust_ledger = [d for d in all_data if str(d.get('Customer ID')).strip().lower() == str(customer_id).strip().lower()]
        
        if not cust_ledger: return

        cust_ledger.sort(key=lambda x: (str(x.get('Date','')), str(x.get('Created Time', '')), str(x.get('Ledger ID', ''))))
        
        running_balance = 0.0
        updated_ledgers = []
        
        for l in cust_ledger:
            d_val = _safe_float(l.get('Debit'))
            c_val = _safe_float(l.get('Credit'))
            running_balance += (d_val - c_val)
            l['Balance'] = running_balance
            updated_ledgers.append(l)
            
        if updated_ledgers:
            write_table('LedgerMaster', updated_ledgers)
    except Exception as e:
        print(f"Error rebuilding ledger: {e}")

# ==========================================
# 5. STORAGE LOGIC
# ==========================================
def upload_image_to_storage(file_name, file_bytes, content_type):
    """Uploads binary image stream to Supabase Storage Bucket."""
    try:
        if not supabase: return None
        supabase.storage.from_('product-images').upload(file_name, file_bytes, {"content-type": content_type, "upsert": "true"})
        return supabase.storage.from_('product-images').get_public_url(file_name)
    except Exception as e:
        print(f"Storage Error: {e}")
        return None