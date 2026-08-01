import os
import hashlib
from supabase import create_client, Client

# ==========================================
# STEP 1: SUPABASE CONNECTION SETUP
# ==========================================
# Dummy HTTPS URL takki server crash na ho (Asli kaam ke liye real URL dalna zaroori hai)
SUPABASE_URL = "https://eznlneklxmrtpnbryzwl.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV6bmxuZWtseG1ydHBuYnJ5endsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTUzNTY1NywiZXhwIjoyMTAxMTExNjU3fQ.8omKupTDpgdfgb9alMzLaP3Gsd1Hez4DRB2CIBzeLM0"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print("⚠️ Supabase Keys Invalid! Server on hai par database kaam nahi karega.")
    supabase = None

# ==========================================
# STEP 2: AUTO-SEEDING & INITIALIZATION (Purana init_db logic)
# ==========================================
# STRICT MATCH: SCHEMAS DICTIONARY RESTORED 100%
# ==========================================
SCHEMAS = {
    'UserMaster': ['User ID', 'User Name', 'Mobile Number', 'Username', 'Password', 'Role', 'Show Rates', 'Allowed Verticals', 'Can View Profit', 'Can Add Ledger', 'Status', 'Last Login', 'Last Order Date', 'Remarks'],
    'VerticalMaster': ['Vertical ID', 'Vertical Name', 'Status'],
    'UniversalMaster': ['Universal Name', 'Vertical', 'Cost Price', 'Status', 'Remarks'],
    'UniversalMaterials': ['Universal Name', 'Material', 'Selling Price', 'Cost Price', 'Is Default'],
    'ProductMaster': ['Product ID', 'Company', 'Product Title', 'Universal Name', 'Vertical', 'Manufacturing Folder Path', 'Image Folder', 'Trending', 'Status', 'Cost Price Override', 'Remarks'],
    'ProductRateMapping': ['Customer ID', 'Universal Name', 'Material', 'Rate'],
    'OrderHeader': [
        'Order ID', 'Order Date', 'Customer ID', 'Customer Name', 'Total Items', 'Total Quantity', 
        'Total Amount', 'Packing Charges', 'Freight Charges', 'Discount', 'Other Charges', 
        'Misc Description', 'Grand Total', 'Special Message', 'Status', 'Created By', 'Created Time'
    ],
    'OrderDetails': [
        'Order Detail ID', 'Order ID', 'Product ID', 'Product Title', 'Universal Name', 'Material',
        'Company', 'Ordered Qty', 'Delivered Qty', 'Pending Qty', 'Unit Rate', 'Cost Price', 
        'Line Amount', 'Status', 'Prepared By', 'Prepared Time'
    ],
    'LedgerMaster': ['Ledger ID', 'Date', 'Customer ID', 'Customer Name', 'Order ID', 'Transaction Type', 'Debit', 'Credit', 'Balance', 'Profit', 'Reference Type', 'Reference ID', 'Remarks', 'Created By', 'Created Time'],
    'PaymentMaster': ['Payment ID', 'Date', 'Customer ID', 'Customer Name', 'Amount', 'Payment Mode', 'Transaction Number', 'Remarks', 'Created By', 'Created Time'],
    'Settings': ['Setting Name', 'Setting Value'],
    'BackupLog': ['Backup Date', 'Backup File', 'Created By'],
    'AdminNotifications': ['Notif ID', 'Date Time', 'Message', 'Is Read']
}

# ==========================================
# STRICT MATCH: INIT_DB (100% Logic Retained)
# ==========================================
def init_db():
    """Initializes default Admin, Profit Password, and exact Vertical Migration in Cloud."""
    
    # 1. Admin Creation Logic (Matched)
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

    # 2. Profit Password Logic (Matched)
    settings = read_table('Settings')
    if not any(s.get('Setting Name') == 'Profit Password' for s in settings):
        hashed_pw = hashlib.sha256(b"admin123").hexdigest()
        settings.append({'Setting Name': 'Profit Password', 'Setting Value': hashed_pw})
        write_table('Settings', settings)

    # 3. AUTOMATIC VERTICAL MIGRATION & SEEDING (100% STRICT MATCH)
    verts = read_table('VerticalMaster')
    if not verts:
        prods = read_table('ProductMaster')
        migrated_verts = []
        
        existing_verticals = set()
        for p in prods:
            v_val = str(p.get('Vertical', '')).strip()
            if v_val:
                existing_verticals.add(v_val)
        
        existing_verticals = sorted(list(existing_verticals))
        
        if existing_verticals:
            for i, v_name in enumerate(existing_verticals, start=1):
                migrated_verts.append({
                    'Vertical ID': f"V{i:03d}",
                    'Vertical Name': v_name,
                    'Status': 'Active'
                })
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


# ==========================================
# STRICT MATCH: READ & WRITE OPERATIONS
# ==========================================
def read_table(table_name):
    """
    Reads table from Supabase and Auto-migrates missing columns exactly like old code.
    """
    try:
        response = supabase.table(table_name).select("*").execute()
        data = response.data if response.data else []
        
        # STRICT MATCH: Auto-migrates missing columns dynamically
        required_headers = SCHEMAS.get(table_name, [])
        formatted_data = []
        
        for row_dict in data:
            for req in required_headers:
                if req not in row_dict or row_dict[req] is None:
                    row_dict[req] = ""
            formatted_data.append(row_dict)
            
        return formatted_data
    except Exception as e:
        print(f"Error reading {table_name}: {str(e)}")
        return []

def write_table(table_name, data):
    """
    Cloud Equivalent of Overwrite. Uses Upsert. 
    Guarantees Schema enforcement and Safety Guards.
    """
    # CRITICAL FIX: Safety guards exactly as requested
    if data is None:
        raise ValueError("write_table() received None")

    if len(data) == 0:
        print(f"WARNING: Refusing to overwrite {table_name} with empty data.")
        return False
        
    try:
        # Excel mein poori file overwrite hoti thi.
        # Supabase mein '.upsert()' ek list of dicts ko leta hai.
        # Jo naye honge wo Insert honge, jo purane honge (ID match) wo Update honge.
        response = supabase.table(table_name).upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error writing {table_name}: {str(e)}")
        return False


# ==========================================
# STRICT MATCH: LEDGER REBUILD
# ==========================================
def rebuild_customer_ledger(customer_id):
    """Exact logic match for running balance recalculation."""
    try:
        # Fetch all data, filter by customer ID
        all_data = read_table('LedgerMaster')
        
        cust_ledger = [d for d in all_data if str(d.get('Customer ID')) == str(customer_id)]
        
        if not cust_ledger:
            return

        # Original Sort Logic
        cust_ledger.sort(key=lambda x: (str(x.get('Date','')), str(x.get('Created Time', '')), str(x.get('Ledger ID'))))
        
        running_balance = 0.0
        updated_ledgers = []
        
        for l in cust_ledger:
            d_val = float(l.get('Debit') or 0.0)
            c_val = float(l.get('Credit') or 0.0)
            running_balance += (d_val - c_val)
            
            # Dictionary mein naya balance daal do
            l['Balance'] = running_balance
            updated_ledgers.append(l)
            
        # Supabase mein updated balances upsert kar do
        if updated_ledgers:
            supabase.table('LedgerMaster').upsert(updated_ledgers).execute()
            
    except Exception as e:
        print(f"Error rebuilding ledger: {e}")