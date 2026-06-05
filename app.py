import streamlit as st
import duckdb
import random
import json
import difflib
import pandas as pd
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
    
    # Inisialisasi tabel po_items untuk menampung multiple item dari 1 PO
    conn.execute("""
        CREATE TABLE IF NOT EXISTS AWE_DB.po_items (
            po_id VARCHAR,
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

tab1, tab2, tab3 = st.tabs(["📝 Buat PO Baru", "📋 PO Aktif", "✏️ Edit & Hapus PO"])

with tab1:
    st.markdown("Silakan lengkapi detail Purchase Order di bawah ini. ID PO akan digenerate secara otomatis.")
    
    # Inisialisasi session state untuk menyimpan daftar item sementara
    if "df_items" not in st.session_state:
        st.session_state.df_items = pd.DataFrame(columns=["Nama Jual", "Barang Konversi", "Berat (gr)"])
        
    st.subheader("1. Data Pelanggan")
    col1, col2 = st.columns(2)
    with col1:
        po_date = st.date_input("Tanggal PO", value=datetime.today())
    with col2:
        customer_name = st.text_input("Nama Customer", placeholder="Contoh: Liao, AHGN dst")
        
    st.markdown("---")
    st.subheader("2. Daftar Item Pesanan")
    
    # Filter global untuk mempermudah pemilihan barang di dalam tabel (Exact Match)
    search_item = st.text_input("🔍 Filter Pilihan Barang di Tabel (Exact Match):", placeholder="Ketik 'B1' untuk membatasi pilihan barang")
    options_filtered = [p for p in products_list if p.lower() == search_item.strip().lower()] if search_item.strip() else products_list

    # Editor Tabel untuk input sekaligus melihat daftar
    edited_df = st.data_editor(
        st.session_state.df_items,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Barang Konversi": st.column_config.MultiselectColumn(
                "Barang Konversi",
                options=options_filtered,
                required=True
            ),
            "Berat (gr)": st.column_config.NumberColumn("Berat (gr)", min_value=0, step=50)
        },
        key="editor_new_po"
    )
    st.session_state.df_items = edited_df

    if not edited_df.empty:
        if st.button("💾 Simpan Semua Data PO", type="primary", use_container_width=True):
            if not customer_name.strip():
                st.error("⚠️ Nama Customer tidak boleh kosong!")
            else:
                po_id = generate_po_id(po_date, customer_name)
                
                try:
                    # Validasi dan proses data dari editor
                    items_summary = []
                    total_weight = 0
                    
                    for _, row in edited_df.iterrows():
                        nj = str(row.get("Nama Jual", "")).strip()
                        bk = row.get("Barang Konversi", [])
                        brt = float(row.get("Berat (gr)", 0))
                        
                        if nj and bk and brt > 0:
                            prod_str = ", ".join(bk)
                            items_summary.append({
                                "name": nj,
                                "detail_gabungan": prod_str,
                                "berat": brt
                            })
                            total_weight += brt
                    
                    if not items_summary:
                        st.error("⚠️ Pastikan data item sudah diisi lengkap (Nama Jual, Barang, dan Berat > 0)!")
                        st.stop()

                    items_json = json.dumps(items_summary)

                    # 1. Simpan Header PO
                    conn.execute("""
                        INSERT INTO AWE_DB.purchase_orders 
                        (po_id, po_date, customer_name, selling_name, product_names, weight)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (po_id, po_date, customer_name, items_json, items_json, total_weight))
                    
                    # 2. Simpan Detail Items PO
                    for item in items_summary:
                        conn.execute("""
                            INSERT INTO AWE_DB.po_items 
                            (po_id, selling_name, product_names, weight)
                            VALUES (?, ?, ?, ?)
                        """, (po_id, item["name"], item["detail_gabungan"], item["berat"]))
                        
                    st.success("✅ Seluruh data PO Berhasil Dibuat!")
                    st.info(f"**ID PO Anda:** `{po_id}`")
                    st.balloons()
                    
                    # Kosongkan kembali daftar item setelah berhasil disimpan
                    st.session_state.df_items = pd.DataFrame(columns=["Nama Jual", "Barang Konversi", "Berat (gr)"])
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Terjadi kesalahan saat menyimpan ke database: {e}")

with tab2:
    st.subheader("Purchase Order Aktif")
    st.markdown("Berikut adalah data Purchase Order aktif yang telah tersimpan di database.")
    
    # Fitur Pencarian
    search_query = st.text_input("🔍 Cari berdasarkan Nama Customer, Nama Jual, atau ID PO", placeholder="Ketik di sini...")
    
    # Query Data: Menggunakan LEFT JOIN agar item-item dalam 1 PO tampil semua bersama data Header-nya
    query = """
        SELECT 
            p.po_id as 'ID PO', 
            p.po_date as 'Tanggal', 
            p.customer_name as 'Customer', 
            COALESCE(i.selling_name, p.selling_name) as 'Nama Jual', 
            COALESCE(i.product_names, p.product_names) as 'Barang Konversi', 
            COALESCE(i.weight, p.weight) as 'Berat (gr)' 
        FROM AWE_DB.purchase_orders p
        LEFT JOIN AWE_DB.po_items i ON p.po_id = i.po_id
    """
    
    # Tambahkan filter ke query jika kolom pencarian diisi
    if search_query:
        query += f" WHERE p.customer_name ILIKE '%{search_query}%' OR p.po_id ILIKE '%{search_query}%' OR i.selling_name ILIKE '%{search_query}%'"
        
    # Urutkan dari PO terbaru
    query += " ORDER BY p.po_date DESC, p.po_id"
    
    try:
        df_po = conn.execute(query).df()
        if df_po.empty:
            st.info("Belum ada data PO yang sesuai.")
        else:
            # Menampilkan dataframe dengan memenuhi seluruh lebar container & hilangkan nomor index row
            st.dataframe(df_po, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Gagal memuat data PO: {e}")

with tab3:
    st.subheader("Edit atau Hapus Purchase Order")
    try:
        # Ambil daftar PO untuk dropdown
        df_po_list = conn.execute("SELECT po_id, customer_name FROM AWE_DB.purchase_orders ORDER BY po_date DESC").df()
        if df_po_list.empty:
            st.info("Belum ada data PO untuk diedit atau dihapus.")
        else:
            # Buat opsi dropdown berupa "ID_PO - Nama Customer"
            po_options = df_po_list['po_id'].astype(str) + " - " + df_po_list['customer_name']
            selected_po_raw = st.selectbox("Pilih PO yang akan diedit/dihapus", options=po_options)
            selected_po_id = selected_po_raw.split(" - ")[0]
            
            # Fetch Data Header
            po_header = conn.execute("SELECT po_date, customer_name FROM AWE_DB.purchase_orders WHERE po_id = ?", (selected_po_id,)).fetchone()
            
            if po_header:
                edit_date, edit_cust = po_header
                
                st.markdown("---")
                with st.form("form_edit_po_header"):
                    st.markdown(f"**1. Edit Data Pelanggan PO:** `{selected_po_id}`")
                    col1, col2 = st.columns(2)
                    with col1:
                        new_date = st.date_input("Tanggal PO", value=edit_date)
                    with col2:
                        new_cust = st.text_input("Nama Customer", value=edit_cust)
                        
                    submitted_edit = st.form_submit_button("Update Pelanggan", use_container_width=True)
                    if submitted_edit:
                        if not new_cust.strip():
                            st.warning("⚠️ Nama Customer tidak boleh kosong!")
                        else:
                            conn.execute("UPDATE AWE_DB.purchase_orders SET po_date=?, customer_name=? WHERE po_id=?", (new_date, new_cust, selected_po_id))
                            st.success(f"✅ Header PO `{selected_po_id}` berhasil diupdate!")
                            if hasattr(st, 'rerun'): st.rerun()
                            else: st.experimental_rerun()
                            
                st.markdown("---")
                st.markdown(f"**2. Edit Daftar Item PO:** `{selected_po_id}`")
                
                # Query semua item berdasarkan po_id dengan menyertakan hidden rowid unik duckdb
                po_items_df = conn.execute("SELECT rowid, selling_name, product_names, weight FROM AWE_DB.po_items WHERE po_id = ?", (selected_po_id,)).df()
                
                if not po_items_df.empty:
                    st.dataframe(po_items_df[['selling_name', 'product_names', 'weight']].rename(columns={'selling_name': 'Nama Jual', 'product_names': 'Barang Konversi', 'weight': 'Berat (gr)'}), use_container_width=True, hide_index=True)
                    
                    item_options = po_items_df['rowid'].astype(str) + " - " + po_items_df['selling_name']
                    selected_item_raw = st.selectbox("Pilih Item yang akan diedit/dihapus", options=item_options)
                    selected_rowid = selected_item_raw.split(" - ")[0]
                    
                    selected_item_data = po_items_df[po_items_df['rowid'].astype(str) == selected_rowid].iloc[0]
                    edit_sell = selected_item_data['selling_name']
                    edit_prods = selected_item_data['product_names']
                    edit_weight = selected_item_data['weight']
                    
                    edit_prod_list = [p.strip() for p in edit_prods.split(",")]
                    valid_edit_prods = [p for p in edit_prod_list if p in products_list]
                    
                    st.markdown(f"**Edit Detail Item:** `{edit_sell}`")
                    new_sell = st.text_input("Nama Jual Barang", value=edit_sell, key="edit_sell_input")
                    
                    # Filter dropdown pada bagian Edit
                    search_edit = st.text_input("🔍 Cari Nama Barang:", key="search_edit_prod")
                    if search_edit.strip():
                        filtered_edit = [p for p in products_list if p.lower() == search_edit.strip().lower()]
                        # Pastikan item yang sedang terpilih tetap ada di daftar agar Streamlit tidak error
                        for p in valid_edit_prods:
                            if p not in filtered_edit:
                                filtered_edit.append(p)
                    else:
                        filtered_edit = products_list

                    new_prods = st.multiselect("Barang Konversi", options=filtered_edit, default=valid_edit_prods)
                    new_weight = st.number_input("Berat Total (gr)", min_value=0, step=50, value=int(edit_weight), key="edit_weight_input")
                    
                    col_upd, col_del = st.columns(2)
                    with col_upd:
                        if st.button("Update Item", use_container_width=True):
                            if not new_sell.strip() or not new_prods or new_weight <= 0:
                                st.warning("⚠️ Lengkapi data item dengan benar!")
                            else:
                                joined_new_prods = ", ".join(new_prods)
                                conn.execute("UPDATE AWE_DB.po_items SET selling_name=?, product_names=?, weight=? WHERE rowid=?", (new_sell, joined_new_prods, new_weight, selected_rowid))
                                st.success("✅ Item berhasil diupdate!")
                                st.rerun()
                    with col_del:
                        if st.button("Hapus Item", use_container_width=True):
                            conn.execute("DELETE FROM AWE_DB.po_items WHERE rowid=?", (selected_rowid,))
                            st.success("✅ Item berhasil dihapus!")
                            st.rerun()
                else:
                    st.info("PO ini tidak memiliki item.")
                    
                st.markdown("**Tambah Item Baru ke PO Ini**")
                search_add_q = st.text_input("🔍 Filter Pilihan Barang Baru (Exact Match):", key="search_add_q")
                options_add = [p for p in products_list if p.lower() == search_add_q.strip().lower()] if search_add_q.strip() else products_list

                if "df_add_items" not in st.session_state:
                    st.session_state.df_add_items = pd.DataFrame(columns=["Nama Jual", "Barang Konversi", "Berat (gr)"])

                df_add = st.data_editor(
                    st.session_state.df_add_items,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "Barang Konversi": st.column_config.MultiselectColumn(options=options_add, required=True),
                    },
                    key="editor_add_tab3"
                )
                st.session_state.df_add_items = df_add

                if st.button("➕ Simpan Item Baru ke PO Ini", use_container_width=True):
                    valid_add = df_add.dropna(subset=["Nama Jual", "Barang Konversi"])
                    for _, row in valid_add.iterrows():
                        nj = str(row["Nama Jual"]).strip()
                        bk = ", ".join(row["Barang Konversi"])
                        bw = float(row["Berat (gr)"])
                        if nj and bk and bw > 0:
                            conn.execute("INSERT INTO AWE_DB.po_items (po_id, selling_name, product_names, weight) VALUES (?, ?, ?, ?)", (selected_po_id, nj, bk, bw))
                    st.success("✅ Item baru berhasil ditambahkan!")
                    st.session_state.df_add_items = pd.DataFrame(columns=["Nama Jual", "Barang Konversi", "Berat (gr)"])
                    st.rerun()
                            
                st.markdown("---")
                st.markdown(f"**3. Hapus Seluruh Data PO:** `{selected_po_id}`")
                if st.button("❌ Hapus Keseluruhan PO Ini", type="primary", use_container_width=True):
                    # Hapus item di database terlebih dahulu, baru hapus header
                    conn.execute("DELETE FROM AWE_DB.po_items WHERE po_id=?", (selected_po_id,))
                    conn.execute("DELETE FROM AWE_DB.purchase_orders WHERE po_id=?", (selected_po_id,))
                    st.success(f"✅ PO `{selected_po_id}` beserta seluruh itemnya berhasil dihapus!")
                    if hasattr(st, 'rerun'): st.rerun()
                    else: st.experimental_rerun()
    except Exception as e:
        st.error(f"❌ Terjadi kesalahan saat memuat form edit/hapus: {e}")
