import streamlit as st
import streamlit.components.v1 as components
import duckdb
import random
import json
import difflib
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
page_title="Sistem Manajemen PO",
page_icon="📦",
layout="centered"
)

# --- SCRIPT UNTUK MENCEGAH SHORTCUT DOWNLOAD (CTRL+J) ---
# Barcode scanner seringkali memicu shortcut browser secara tidak sengaja
components.html(
    """
    <script>
    const blockShortcut = function(e) {
        // Memblokir Ctrl+J (74), Ctrl+S (83), dan Ctrl+N (78)
        if ((e.ctrlKey || e.metaKey) && [74, 83, 78].includes(e.keyCode)) {
            e.preventDefault();
            e.stopImmediatePropagation();
        }
    };
    // Pasang listener di parent window dan di dalam iframe (capturing phase)
    window.parent.document.addEventListener('keydown', blockShortcut, true);
    document.addEventListener('keydown', blockShortcut, true);
    </script>
    """,
    height=0,
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
    st.markdown("Silakan lengkapi detail Purchase Order di bawah ini.")

    # Inisialisasi session state untuk menyimpan daftar item sementara
    if "po_items" not in st.session_state:
        st.session_state.po_items = []

    st.subheader("1. Data Pelanggan")
    col1, col2 = st.columns(2)
    with col1:
        po_date = st.date_input("Tanggal PO", value=datetime.today())
    with col2:
        customer_name = st.text_input("Nama Customer", placeholder="Contoh: Liao, AHGN dst")

    st.markdown("---")
    st.subheader("2. Tambah Detail Pesanan (Multiple Item)")

    # Gunakan FORM untuk membungkus input barang agar Enter tidak langsung memicu rerun aplikasi
    with st.form("form_tambah_barang", clear_on_submit=True):
        selling_name = st.text_input("Nama Jual Barang", placeholder="Contoh: N1, N1-BC, N2-H dst")

        selected_products = st.multiselect(
            "Konversi (Pilih nama barang untuk nama jual)",
            options=products_list,
            placeholder="Ketik untuk mencari barang..."
        )
        
        weight = st.number_input("Berat Total (gr)", min_value=0, step=50)
        
        submit_item = st.form_submit_button("➕ Tambah Item ke Daftar", use_container_width=True)

        if submit_item:
            # --- VALIDASI DUPLIKAT & KEMIRIPAN (CASE & TYPO) ---
            input_name = selling_name.strip()
            is_duplicate = False
            similar_match = None

            for item in st.session_state.po_items:
                existing_name = item["Nama Jual"]
                if input_name.lower() == existing_name.lower():
                    is_duplicate = True
                    break
                if not similar_match and difflib.SequenceMatcher(None, input_name.lower(), existing_name.lower()).ratio() > 0.8:
                    similar_match = existing_name

            if not selling_name.strip() or not selected_products or weight <= 0:
                st.warning("⚠️ Lengkapi data item (Nama Jual, Barang, dan Berat > 0)!")
            elif is_duplicate:
                st.error(f"🚫 Gagal: Item '{input_name}' sudah ada di daftar!")
            else:
                if similar_match:
                    st.warning(f"⚠️ Peringatan: Nama '{input_name}' sangat mirip dengan '{similar_match}'. Mohon periksa kembali apakah ada typo.")

                st.session_state.po_items.append({
                    "Nama Jual": selling_name,
                    "Barang Konversi": ", ".join(selected_products),
                    "Berat (gr)": weight
                })
                st.success("✅ Item berhasil ditambahkan ke daftar!")
                st.rerun()

    # Tampilkan daftar item dan tombol simpan utama
    if st.session_state.po_items:
        st.markdown("**Daftar Item dalam PO ini:**")
        
        # Menampilkan header tabel manual
        col_header_name, col_header_prods, col_header_weight, col_header_delete = st.columns([0.3, 0.4, 0.15, 0.15])
        with col_header_name:
            st.write("**Nama Jual**")
        with col_header_prods:
            st.write("**Barang Konversi**")
        with col_header_weight:
            st.write("**Berat (gr)**")
        with col_header_delete:
            st.write("**Aksi**")
        st.markdown("---") # Garis pemisah

        # Menampilkan setiap item dengan tombol hapus
        for i, item in enumerate(st.session_state.po_items):
            col_name, col_prods, col_weight, col_delete = st.columns([0.3, 0.4, 0.15, 0.15])
            with col_name:
                st.write(item["Nama Jual"])
            with col_prods:
                st.write(item["Barang Konversi"])
            with col_weight:
                st.write(f"{item['Berat (gr)']:.0f} gr")
            with col_delete:
                if st.button("🗑️ Hapus", key=f"delete_item_{i}"):
                    del st.session_state.po_items[i]
                    st.success("Item berhasil dihapus dari daftar.")
                    st.rerun()
        st.markdown("---") # Garis pemisah setelah daftar item

        if st.button("💾 Simpan Semua Data PO", type="primary", use_container_width=True):
            if not customer_name.strip():
                st.error("⚠️ Nama Customer tidak boleh kosong!")
            else:
                po_id = generate_po_id(po_date, customer_name)

                try:
                    # Menghitung total berat dan memformat data items ke JSON
                    total_weight = sum(item["Berat (gr)"] for item in st.session_state.po_items)
                    items_summary = [
                        {
                            "name": item["Nama Jual"],
                            "detail_gabungan": item["Barang Konversi"],
                            "berat": float(item["Berat (gr)"])
                        }
                        for item in st.session_state.po_items
                    ]
                    items_json = json.dumps(items_summary)

                    # 1. Simpan Header PO
                    conn.execute("""
                        INSERT INTO AWE_DB.purchase_orders 
                        (po_id, po_date, customer_name, selling_name, product_names, weight)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (po_id, po_date, customer_name, items_json, items_json, total_weight))

                    # 2. Simpan Detail Items PO
                    # Optimasi: Batch Insert lebih cepat daripada looping execute
                    items_to_insert = [
                        (po_id, item["Nama Jual"], item["Barang Konversi"], item["Berat (gr)"])
                        for item in st.session_state.po_items
                    ]
                    conn.executemany("""
                        INSERT INTO AWE_DB.po_items (po_id, selling_name, product_names, weight)
                        VALUES (?, ?, ?, ?)
                    """, items_to_insert)

                    st.success("✅ Seluruh data PO Berhasil Dibuat!")
                    st.info(f"**ID PO Anda:** `{po_id}`")
                    st.balloons()

                    # Kosongkan kembali daftar item setelah berhasil disimpan
                    st.session_state.po_items = []
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Terjadi kesalahan saat menyimpan ke database: {e}")

with tab2:
    st.subheader("Purchase Order Aktif")
    st.markdown("Berikut adalah data Purchase Order aktif yang telah tersimpan di database.")

    # Fitur Pencarian
    search_po = st.text_input("🔍 Cari berdasarkan Nama Customer, Nama Jual, atau ID PO", placeholder="Ketik di sini...", key="search_po_active")

    # Base Query
    query_base = """
        SELECT 
            p.po_id as 'ID PO', 
            p.po_date as 'Tanggal', 
            p.customer_name as 'Customer', 
            i.selling_name as 'Nama Jual', 
            COALESCE(i.product_names, p.product_names) as 'Barang Konversi', 
            COALESCE(i.weight, p.weight) as 'Berat (gr)' 
        FROM AWE_DB.purchase_orders p
        LEFT JOIN AWE_DB.po_items i ON p.po_id = i.po_id
    """

    # Tambahkan filter ke query jika kolom pencarian diisi
    params = []
    if search_po:
        query_base += " WHERE p.customer_name ILIKE ? OR p.po_id ILIKE ? OR i.selling_name ILIKE ?"
        search_term = f"%{search_po}%"
        params = [search_term, search_term, search_term]

    query_base += " ORDER BY p.po_date DESC, p.po_id"

    try:
        df_po = conn.execute(query_base, params).df()
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
        # Optimasi Performa: Jangan ambil semua data, cukup 50-100 PO terbaru saja 
        # atau gunakan pencarian untuk membatasi data yang ditarik ke browser.
        search_edit = st.text_input("🔍 Cari ID PO atau Nama Customer untuk diedit", placeholder="Ketik minimal 3 huruf...", key="search_edit_selector")
        
        query_list = "SELECT po_id, customer_name FROM AWE_DB.purchase_orders "
        if len(search_edit) >= 3:
            query_list += f"WHERE po_id ILIKE '%{search_edit}%' OR customer_name ILIKE '%{search_edit}%' "
        query_list += "ORDER BY po_date DESC LIMIT 50"

        df_po_list = conn.execute(query_list).df()
        
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
                            st.rerun()

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

                    # Gunakan products_list langsung, multiselect sudah punya fitur pencarian internal yang lebih cepat
                    new_prods = st.multiselect("Barang Konversi", options=products_list, default=valid_edit_prods, key="edit_prods_multi")
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
                add_sell = st.text_input("Nama Jual Barang Baru", placeholder="Contoh: N1, N1-BC, N2-H dst", key="add_sell_new")

                # Optimasi: Hapus filter manual, gunakan pencarian bawaan multiselect
                add_prods = st.multiselect("Barang Konversi Baru", options=products_list, placeholder="Pilih barang", key="add_prods_multi")
                add_weight = st.number_input("Berat Total Baru (gr)", min_value=0, step=50, key="add_weight_new")

                if st.button("➕ Tambah Item", use_container_width=True):
                    # --- VALIDASI DUPLIKAT & KEMIRIPAN ---
                    input_add_name = add_sell.strip()
                    is_duplicate_add = False
                    similar_match_add = None

                    for existing_name in po_items_df['selling_name']:
                        if input_add_name.lower() == existing_name.lower():
                            is_duplicate_add = True
                            break
                        if not similar_match_add and difflib.SequenceMatcher(None, input_add_name.lower(), existing_name.lower()).ratio() > 0.8:
                            similar_match_add = existing_name

                    if not add_sell.strip() or not add_prods or add_weight <= 0:
                        st.warning("⚠️ Lengkapi data item baru dengan benar!")
                    elif is_duplicate_add:
                        st.error(f"🚫 Item '{input_add_name}' sudah ada di PO ini!")
                    else:
                        if similar_match_add:
                            st.warning(f"⚠️ Nama '{input_add_name}' sangat mirip dengan '{similar_match_add}'. Mohon periksa typo.")

                        joined_add_prods = ", ".join(add_prods)
                        conn.execute("INSERT INTO AWE_DB.po_items (po_id, selling_name, product_names, weight) VALUES (?, ?, ?, ?)", (selected_po_id, add_sell, joined_add_prods, add_weight))
                        st.success("✅ Item baru berhasil ditambahkan!")
                        st.rerun()

                st.markdown("---")
                st.markdown(f"**3. Hapus Seluruh Data PO:** `{selected_po_id}`")
                if st.button("❌ Hapus Keseluruhan PO Ini", type="primary", use_container_width=True):
                    # Hapus item di database terlebih dahulu, baru hapus header
                    conn.execute("DELETE FROM AWE_DB.po_items WHERE po_id=?", (selected_po_id,))
                    conn.execute("DELETE FROM AWE_DB.purchase_orders WHERE po_id=?", (selected_po_id,))
                    st.success(f"✅ PO `{selected_po_id}` beserta seluruh itemnya berhasil dihapus!")
                    st.rerun()
    except Exception as e:
        st.error(f"❌ Terjadi kesalahan saat memuat form edit/hapus: {e}")