import os
import json
import asyncio
import requests
import io
import pygame
import ssl
import certifi
import time
import urllib3

# Non‐aktifkan peringatan SSL sementara (untuk HTTPS tanpa verifikasi sertifikat)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Pastikan paket-paket berikut sudah di‐install:
#    pip install requests elevenlabs TikTokLive pygame
try:
    from elevenlabs import ElevenLabs, VoiceSettings
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent
    #                     ^^^^^^^^^^    ^^^^^^^^^^^    ^^^^^^^^^^^^^
    #  (JANGAN import JoinEvent, agar tidak ada log “bergabung ke live”)
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Silakan install paket yang dibutuhkan dengan:")
    print("    pip install requests elevenlabs TikTokLive pygame")
    exit(1)

# ==========================
# 1) API Keys dan Konfigurasi
# ==========================
ELEVENLABS_API_KEY = "sk_c9113e0c8fab6e1230972d58268a7fecac904f2ef8b2cef0"
AGENT_ENDPOINT     = "https://agent-49f595c4de01a4496dac-hwy7f.ondigitalocean.app/api/v1/chat/completions"
AGENT_API_KEY      = "p4DP26zWc-st3VBmhg3qjZ2m5OfV2HJn"

# ==========================
# 2) Inisialisasi Client
# ==========================
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Ganti "droness29" dengan username Live TikTok Anda (tanpa '@')
tiktok_client = TikTokLiveClient(unique_id="droness29")

# Inisialisasi mixer pygame untuk memutar TTS
pygame.mixer.init()

# ==========================
# 3) Variabel Global
# ==========================
last_comment_time = None       # dipakai untuk keep_alive
connection_status = False      # menandai apakah client sudah terhubung

# ==========================
# 3a) Antrean untuk komentar
# ==========================
# Semua komentar baru akan masuk ke sini. Kita proses satu‐per‐satu:
comment_queue = asyncio.Queue()

# ==========================
# 4) Load Product Knowledge (opsional)
# ==========================
try:
    with open('djiair3s.json', 'r', encoding='utf-8') as f:
        product_knowledge = json.load(f)
    print("Product Knowledge berhasil dimuat")
except Exception as e:
    print(f"Error saat memuat Product Knowledge: {e}")
    product_knowledge = {}

# ==========================
# 5) Fungsi chat_with_agent
# ==========================
async def chat_with_agent(prompt: str) -> str:
    """
    Kirim prompt ke Agent API, kembalikan jawaban maksimal 50 kata.
    """
    try:
        system_prompt = (
            "Anda adalah asisten AI bernama Lucy yang menjawab dengan bahasa Indonesia "
            "dan respons maksimal 50 kata. Anda adalah ahli tentang DJI Air 3S."
        )
        if product_knowledge:
            system_prompt += "\n\nBerikut adalah informasi tentang DJI Air 3S yang perlu Anda ketahui:\n"
            system_prompt += json.dumps(product_knowledge, ensure_ascii=False)
            system_prompt += (
                "\n\nJawab pertanyaan tentang DJI Air 3S berdasarkan informasi di atas jika relevan. "
                "Jika ditanya tentang spesifikasi, berikan informasi akurat. "
                "Pastikan menyebutkan bahwa ini adalah DJI Air 3S dalam jawaban Anda."
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AGENT_API_KEY}"
        }
        payload = {
            "model": "llama3.3-70b-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt}
            ],
            "max_tokens": 100,
            "temperature": 0.7
        }

        # Kirim request di thread terpisah agar tidak blocking event loop
        async_response = await asyncio.to_thread(
            requests.post,
            AGENT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=10
        )

        if async_response.status_code == 200:
            data = async_response.json()
            full_response = data["choices"][0]["message"]["content"]
            return ' '.join(full_response.split()[:50])  # ambil hanya 50 kata
        else:
            print(f"Agent API Error: {async_response.status_code} - {async_response.text}")
            return "Maaf, saya mengalami gangguan teknis."
    except Exception as e:
        print(f"Error dalam chat_with_agent: {e}")
        return "Maaf, saya sedang tidak bisa merespon."


# ==========================
# 6) Fungsi text_to_speech_and_play
# ==========================
async def text_to_speech_and_play(text: str):
    """
    Mengonversi teks menjadi audio dengan ElevenLabs lalu memutar via pygame.
    Fungsi di-await agar menunggu hingga audio selesai (non-blocking terhadap event loop).
    """
    try:
        print(f"[TTS] Generating audio untuk: {text[:50]}...")
        audio_generator = eleven_client.text_to_speech.convert(
            voice_id="iWydkXKoiVtvdn4vLKp9",
            optimize_streaming_latency=0,
            output_format="mp3_22050_32",
            text=text,
            model_id="eleven_flash_v2_5",
            voice_settings=VoiceSettings(
                stability=0.1,
                similarity_boost=0.3,
                style=0.2,
            ),
        )

        chunks = []
        for chunk in audio_generator:
            if chunk:
                chunks.append(chunk)

        audio_data = b''.join(chunks)
        audio_file = io.BytesIO(audio_data)

        # Muat dan putar audio di thread terpisah
        await asyncio.to_thread(pygame.mixer.music.load, audio_file)
        await asyncio.to_thread(pygame.mixer.music.play)

        # Tunggu hingga audio benar-benar selesai
        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)

        print("[TTS] Audio playback selesai")
    except Exception as e:
        print(f"Error dalam text_to_speech_and_play: {e}")


# ==========================
# 7) Handler ConnectEvent
# ==========================
@tiktok_client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    """
    Dipanggil sekali ketika sukses join ke Live TikTok.
    """
    global connection_status, last_comment_time
    connection_status = True
    print(f"✅ BERHASIL TERHUBUNG ke @{event.unique_id} (Room ID: {tiktok_client.room_id})")
    print(f"Viewer count: {getattr(event, 'viewer_count', 'N/A')}")

    last_comment_time = time.time()
    welcome_msg = "Lucy AI siap membantu! Silakan tanyakan tentang DJI Air 3S."
    print(f"Lucy: {welcome_msg}")
    await text_to_speech_and_play(welcome_msg)


# ==========================
# 8) Handler DisconnectEvent
# ==========================
@tiktok_client.on(DisconnectEvent)
async def on_disconnect(event):
    """
    Dipanggil ketika koneksi Live TikTok terputus.
    """
    global connection_status
    connection_status = False
    print("❌ TERPUTUS dari live stream")


# ==========================
# 9) Handler CommentEvent → Masukkan ke antrean
# ==========================
@tiktok_client.on(CommentEvent)
async def on_comment(event: CommentEvent):
    """
    Setiap komentar baru akan langsung dimasukkan ke antrean.
    Proses TTS-nya terjadi di process_comment_queue() secara paralel.
    """
    comment_text = event.comment.strip()
    if not comment_text:
        return

    username = event.user.nickname
    # Masukkan tuple (username, teks komentar) ke antrean:
    await comment_queue.put((username, comment_text))


# ==========================
# 10) Proses Antrean Komentar Satu-per-Satu
# ==========================
async def process_comment_queue():
    """
    Loop tak terhingga: ambil satu komentar dari antrean → TTS → loop lagi.
    Jika antrean kosong, `await comment_queue.get()` akan otomatis menunggu tanpa memakan CPU.
    """
    print("🚀 Memulai pemrosesan antrean komentar...")
    while True:
        try:
            username, comment_text = await comment_queue.get()

            # CETAK HANYA SATU BARIS DEBUG: komentar yang sedang diproses
            print(f"[DEBUG] Sedang memproses komentar: {username} → “{comment_text}”")

            # Kirim prompt ke Agent, lalu cetak hasil ringkasan
            jawaban = await chat_with_agent(f"Pengguna {username} bertanya: {comment_text}. Jelaskan tentang DJI Air 3S.")
            print(f"🤖 Lucy: {jawaban}")

            # Proses TTS hingga selesai (baris ini akan mem­block fungsi ini sampai audio selesai)
            await text_to_speech_and_play(jawaban)

            # Update waktu terakhir komentar, dipakai keep_alive
            global last_comment_time
            last_comment_time = time.time()

            comment_queue.task_done()

        except Exception as e:
            print(f"❌ Error dalam process_comment_queue: {e}")
            # Jika error, tunggu 1 detik lalu lanjut loop
            await asyncio.sleep(1)


# ==========================
# 11) Fungsi generate_product_promo (auto-promo jika 2 menit kosong)
# ==========================
async def generate_product_promo() -> str:
    """
    Menghasilkan teks promo singkat tentang DJI Air 3S berdasarkan product_knowledge.
    Jika JSON tidak ada, pakai fallback sederhana.
    """
    if not product_knowledge:
        return (
            "DJI Air 3S adalah drone ringkas dan canggih, "
            "cocok untuk foto dan video udara. Dengan kamera ganda dan teknologi pintar, "
            "drone ini sempurna untuk kreativitas Anda."
        )

    import random
    choices = ['deskripsi', 'fitur', 'kamera', 'video', 'harga', 'target']
    t = random.choice(choices)

    try:
        if t == 'deskripsi':
            return f"DJI Air 3S: {product_knowledge.get('deskripsi', 'Drone canggih dengan kamera ganda')}"
        if t == 'fitur':
            fitur = product_knowledge.get('fitur_utama', {})
            if fitur:
                rk = random.choice(list(fitur.keys()))
                rd = fitur[rk].get('deskripsi', '')
                return f"Fitur {rk}: {rd}"
        if t == 'kamera':
            kam = product_knowledge.get('fitur_utama', {}).get('sistem_kamera_ganda', {})
            if kam:
                kt = random.choice(['kamera_utama', 'kamera_telefoto'])
                det = kam.get(kt, {})
                return (
                    f"DJI Air 3S dilengkapi {kt} beresolusi {det.get('resolusi','')} "
                    f"aperture {det.get('aperture','')}. {det.get('keunggulan','')}"
                )
        if t == 'video':
            vid = product_knowledge.get('fitur_utama', {}).get('perekaman_video', {})
            if vid:
                return (
                    f"Rekam video 4K HDR {vid.get('4K_HDR','')} atau slow-motion {vid.get('4K_slow_motion','')}."
                )
        if t == 'harga':
            h = product_knowledge.get('harga_dan_ketersediaan', {})
            return f"DJI Air 3S {h.get('perkiraan_harga','terjangkau')} {h.get('deskripsi','')}"
        if t == 'target':
            trg = product_knowledge.get('target_pengguna', {})
            ut  = random.choice(['fotografer','videografer','konten_kreator'])
            return f"DJI Air 3S cocok untuk {ut}. {trg.get(ut,'')}"
    except Exception as e:
        print(f"Error generating promo: {e}")

    return "DJI Air 3S: Drone canggih untuk foto dan video berkualitas tinggi."


# ==========================
# 12) Fungsi keep_alive (auto-promo setiap 2 menit kosong)
# ==========================
async def keep_alive():
    """
    Jika 120 detik telah berlalu sejak komentar terakhir
    dan antrean kosong, maka jalankan auto-promo.
    """
    global last_comment_time
    last_comment_time = time.time()

    while True:
        try:
            now = time.time()
            # Cek: jika 120 detik berlalu, dan antrean komentar kosong
            if (
                last_comment_time is not None
                and (now - last_comment_time) > 60
                and comment_queue.empty()
            ):
                print("⏰ 2 menit tanpa komentar & antrean kosong → Auto-promo")
                promo = await generate_product_promo()
                print(f"📢 Auto-promo: {promo}")
                await text_to_speech_and_play(promo)
                last_comment_time = time.time()

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error dalam keep_alive: {e}")
            await asyncio.sleep(5)


# ==========================
# 13) Fungsi connection_monitor
# ==========================
async def connection_monitor():
    """
    Cek status koneksi tiap 30 detik. Jika terputus, coba reconnect.
    """
    while True:
        try:
            if not connection_status:
                print("⚠️ Koneksi terputus, mencoba reconnect…")
                await tiktok_client.connect()
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Error dalam connection_monitor: {e}")
            await asyncio.sleep(10)


# ==========================
# 14) Fungsi test_tiktok_connection
# ==========================
async def test_tiktok_connection() -> bool:
    """
    Coba connect sekali untuk memastikan client bisa terhubung.
    Setelah test ini, kita akan buat koneksi long-running di main().
    """
    try:
        print("🔗 Testing koneksi TikTok Live (test only)…")
        ssl._create_default_https_context = ssl._create_unverified_context
        await asyncio.wait_for(tiktok_client.connect(), timeout=30.0)
        await asyncio.sleep(3)
        if connection_status:
            print("✅ Test koneksi TikTok Live berhasil")
            return True
        else:
            print("❌ Test koneksi TikTok Live gagal")
            return False
    except Exception as e:
        print(f"❌ Test TikTokLiveClient gagal: {e}")
        return False


# ==========================
# 15) Fungsi test_agent_connection
# ==========================
async def test_agent_connection() -> bool:
    """
    Cek apakah Agent API merespon.
    """
    try:
        print("🔄 Testing koneksi ke Agent API…")
        res = await chat_with_agent("Halo, ini test koneksi")
        print(f"✅ Test Agent berhasil: {res}")
        return True
    except Exception as e:
        print(f"❌ Test Agent gagal: {e}")
        return False


# ==========================
# 16) Fungsi test_elevenlabs_connection
# ==========================
async def test_elevenlabs_connection() -> bool:
    """
    Cek apakah ElevenLabs API merespon setidaknya satu chunk.
    """
    try:
        print("🔄 Testing koneksi ke ElevenLabs…")
        gen = eleven_client.text_to_speech.convert(
            voice_id="iWydkXKoiVtvdn4vLKp9",
            optimize_streaming_latency=0,
            output_format="mp3_22050_32",
            text="Test koneksi",
            model_id="eleven_flash_v2_5",
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.5,
                style=0.2,
            ),
        )
        first = next(gen, None)
        if first:
            print("✅ ElevenLabs test OK")
            return True
        else:
            print("❌ ElevenLabs test Gagal: Tidak ada chunk audio")
            return False
    except Exception as e:
        print(f"❌ Test ElevenLabs error: {e}")
        return False


# ==========================
# 17) Fungsi main
# ==========================
async def main():
    print("=== Lucy AI Assistant untuk TikTok Live ===")
    print("🚀 Memulai sistem…")

    # 1) Test koneksi ke Agent API
    print("\n1️⃣ Testing Agent API…")
    if not await test_agent_connection():
        print("❌ Tidak dapat terhubung ke Agent API. Berhenti.")
        return

    # 2) Test koneksi ke ElevenLabs
    print("\n2️⃣ Testing ElevenLabs…")
    if not await test_elevenlabs_connection():
        print("⚠️ ElevenLabs tidak dapat diakses. Fitur suara non-aktif.")
    else:
        print("✅ ElevenLabs siap")

    # 3) Test koneksi ke TikTok Live (sekali saja)
    print("\n3️⃣ Testing koneksi TikTok Live (test)…")
    if not await test_tiktok_connection():
        print("❌ Gagal menguji koneksi TikTok Live. Berhenti.")
        return

    # 4) Setelah test, jalankan lagi connect() sebagai long-running task
    print("\n🚀 Menjalankan koneksi TikTokLiveClient secara long-running…")
    ssl._create_default_https_context = ssl._create_unverified_context
    # Buat task terpisah agar event listener on_comment terus aktif:
    asyncio.create_task(tiktok_client.connect())

    # Beri jeda singkat supaya on_connect bisa dipicu dulu
    await asyncio.sleep(2)

    print("\n✅ Semua sistem siap! Mulai monitoring komentar…")
    print("💬 Menunggu komentar dari viewers…")

    # Jalankan tiga task paralel:
    #  - process_comment_queue   (memproses komentar satu per satu)
    #  - keep_alive              (auto-promo kalau 2 menit kosong)
    #  - connection_monitor      (cek koneksi tiap 30 detik & reconnect jika perlu)
    tasks = [
        process_comment_queue(),
        keep_alive(),
        connection_monitor()
    ]
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n⏹️ Program dihentikan oleh pengguna")
    except Exception as e:
        print(f"❌ Error dalam main loop: {e}")
    finally:
        print("🔌 Menutup koneksi…")
        try:
            await tiktok_client.disconnect()
        except:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Program dihentikan")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
