# journal-corpus

**journal-corpus** adalah proyek pengumpulan dan normalisasi data jurnal ilmiah dari berbagai sumber terpercaya, baik nasional maupun internasional. Proyek ini bertujuan untuk menyediakan dataset berkualitas tinggi yang dapat digunakan untuk penelitian, analisis bibliometrik, pengembangan NLP akademik, dan deteksi plagiarisme.

## Sumber Data

Data dikumpulkan dari berbagai platform dan repositori jurnal berikut:

- Google Scholar (menggunakan library `scholarly`)
- DOAJ (Directory of Open Access Journals) dengan metadata lengkap
- arXiv untuk preprint akademik
- PubMed untuk jurnal medis dan kesehatan
- SINTA (Science and Technology Index Indonesia)
- Portal Garuda
- Semantic Scholar untuk metadata dan referensi tambahan
- Repository institusi dalam negeri (UI, ITB, UGM, Unair, ITS)

## Informasi yang Dikumpulkan

Setiap entri jurnal dalam corpus akan mencakup informasi berikut:

- Judul artikel
- Abstrak lengkap
- Nama penulis dan afiliasi institusi
- Kata kunci (keywords)
- DOI (Digital Object Identifier)
- URL artikel dan URL PDF (jika tersedia)
- Jumlah sitasi
- Nomor halaman, volume, dan issue
- Nama penerbit
- Tahun terbit
- Bahasa artikel
- Bidang subjek atau kategori
- Teks lengkap artikel (jika memungkinkan)
- Daftar referensi
- Tanggal pengumpulan data

## Tujuan Proyek

- Menyediakan dataset jurnal akademik dalam format terstruktur
- Mempermudah pencarian dan analisis metadata ilmiah
- Mendukung penelitian di bidang NLP akademik, ekstraksi informasi, dan deteksi plagiarisme

## Lisensi

Proyek ini bersifat open-source. Namun, pengguna bertanggung jawab untuk mematuhi hak cipta dan lisensi dari masing-masing sumber jurnal.
