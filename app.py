import streamlit as st
import duckdb
import random
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="Sistem Manajemen PO",
    page_icon="📦",
    layout="centered"
)

# --- FUNGSI KONEKSI DATABASE ---
# Menggunakan cache agar koneksi tidak direstart terus-menerus setiap interaksi
@st.cache_resource
def init_connection():
    # Pastikan Anda sudah menyimpan MOTHERDUCK_TOKEN di Streamlit Secrets
    token = st.secrets["MOTHERDUCK_TOKEN"]
    # Koneksi ke MotherDuck (Ganti sesuai konfigurasi jika perlu)
    conn = duckdb.connect(f"md:AWE_DB?motherduck_token={token}")
    
    # Inisialisasi tabel purchase_orders jika belum ada
    conn.execute("""
        CREATE TABLE IF NOT EXISTS AWE_DB.purchase_orders (
            po_id VARCHAR PRIMARY KEY,
            po_date DATE,
            customer_name VARCHAR,
            selling_name VARCHAR,
            product_names VARCHAR,
            weight DOUBLE
        );
    """)
    
    # Tambahkan kolom baru 'selling_name' jika tabel sebelumnya sudah terlanjur dibuat
    try:
        conn.execute("ALTER TABLE AWE_DB.purchase_orders ADD COLUMN selling_name VARCHAR")
    except Exception:
        pass # Abaikan jika kolom sudah ada
    return conn

conn = init_connection()

# --- FUNGSI AMBIL DATA BARANG ---
@st.cache_data(ttl=600) # Cache data selama 10 menit
def fetch_products():
    try:
        # Mengambil data product_name dari tabel product_catalog
        df = conn.execute("SELECT product_name FROM AWE_DB.product_catalog").df()
        return df['product_name'].tolist()
    except Exception as e:
        st.error(f"Gagal memuat katalog produk: {e}")
        # Dummy data jika tabel gagal diload untuk keperluan testing UI
        return ["Kopi Arabika", "Gula Pasir 1Kg", "Susu UHT", "Minyak Goreng"]

# --- FUNGSI GENERATE PO ID ---
def generate_po_id(po_date, customer_name):
    # Format tanggal: YYYYMMDD (contoh: 20231025)
    date_str = po_date.strftime("%Y%m%d")
    
    # Ambil 3 huruf pertama customer, buang spasi, jadikan huruf besar
    cust_code = "".join(char for char in customer_name if char.isalnum())[:3].upper()
    if not cust_code:
        cust_code = "CST" # Fallback jika nama aneh
        
    # Angka random unik 5 digit
    random_num = random.randint(10000, 99999)
    
    # Gabungkan menjadi Primary Key
    return f"PO-{date_str}-{cust_code}-{random_num}"


# --- ANTARMUKA APLIKASI (UI) ---
st.title("📦 Sistem Manajemen Purchase Order")

# Tarik data produk dari MotherDuck
products_list = fetch_products()

tab1, tab2 = st.tabs(["📝 Buat PO Baru", "📋 Daftar PO"])

with tab1:
    st.markdown("Silakan lengkapi detail Purchase Order di bawah ini. ID PO akan digenerate secara otomatis.")
    
    with st.form("form_create_po"):
        st.subheader("Data Pelanggan")
        col1, col2 = st.columns(2)
        with col1:
            po_date = st.date_input("Tanggal PO", value=datetime.today())
        with col2:
            customer_name = st.text_input("Nama Customer", placeholder="Contoh: PT. Maju Jaya")
        
        st.markdown("---")
        st.subheader("Detail Pesanan")
        
        selling_name = st.text_input("Nama Jual Barang", placeholder="Contoh: Paket Sembako Hemat")
        
        # Multiselect untuk menggabungkan beberapa barang
        selected_products = st.multiselect(
            "Barang Konversi (Pilih barang pembentuk nama jual)",
            options=products_list,
            placeholder="Pilih barang dari katalog..."
        )
        
        # Input berat
        weight = st.number_input("Berat Total (Kg)", min_value=0.0, format="%.2f", step=0.5)
        
        st.markdown("---")
        # Tombol Submit
        submitted = st.form_submit_button("Simpan PO", use_container_width=True)

        if submitted:
            # Validasi input
            if not customer_name.strip():
                st.warning("⚠️ Nama Customer tidak boleh kosong!")
            elif not selling_name.strip():
                st.warning("⚠️ Nama Jual Barang tidak boleh kosong!")
            elif not selected_products:
                st.warning("⚠️ Silakan pilih minimal 1 barang!")
            elif weight <= 0:
                st.warning("⚠️ Berat tidak boleh 0!")
            else:
                # Generate Data
                po_id = generate_po_id(po_date, customer_name)
                joined_products = ", ".join(selected_products) # Menggabungkan nama barang
                
                try:
                    # Simpan ke MotherDuck
                    conn.execute("""
                        INSERT INTO AWE_DB.purchase_orders 
                        (po_id, po_date, customer_name, selling_name, product_names, weight)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (po_id, po_date, customer_name, selling_name, joined_products, weight))
                    
                    # Menampilkan sukses dengan UI yang menarik
                    st.success(f"✅ PO Berhasil Dibuat!")
                    st.info(f"**ID PO Anda:** `{po_id}`")
                    st.balloons() # Efek balon di Streamlit
                    
                except Exception as e:
                    st.error(f"❌ Terjadi kesalahan saat menyimpan ke database: {e}")

with tab2:
    st.subheader("Daftar Purchase Order")
    st.markdown("Berikut adalah data Purchase Order yang telah tersimpan di database.")
    
    # Fitur Pencarian
    search_query = st.text_input("🔍 Cari berdasarkan Nama Customer, Nama Jual, atau ID PO", placeholder="Ketik di sini...")
    
    # Query Data (Gunakan alias agar rapi di dataframe Streamlit)
    query = "SELECT po_id as 'ID PO', po_date as 'Tanggal', customer_name as 'Customer', selling_name as 'Nama Jual', product_names as 'Barang Konversi', weight as 'Berat (Kg)' FROM AWE_DB.purchase_orders"
    
    # Tambahkan filter ke query jika kolom pencarian diisi
    if search_query:
        query += f" WHERE customer_name ILIKE '%{search_query}%' OR po_id ILIKE '%{search_query}%' OR selling_name ILIKE '%{search_query}%'"
        
    # Urutkan dari PO terbaru
    query += " ORDER BY po_date DESC"
    
    try:
        df_po = conn.execute(query).df()
        if df_po.empty:
            st.info("Belum ada data PO yang sesuai.")
        else:
            # Menampilkan dataframe dengan memenuhi seluruh lebar container & hilangkan nomor index row
            st.dataframe(df_po, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Gagal memuat data PO: {e}")
