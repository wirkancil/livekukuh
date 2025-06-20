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
tiktok_client = TikTokLiveClient(unique_id="martabaknikmat.id")

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
# 4) (Dihapus) Load Product Knowledge
# ==========================
# Kita tidak menggunakan product_knowledge di versi ini.

# ==========================
# 5) Fungsi chat_with_agent (social chatbot)
# ==========================
async def chat_with_agent(prompt: str) -> str:
    """
    Kirim prompt ke Agent API untuk mendapatkan respons singkat (maksimal ~50 kata).
    Lucy berperan sebagai teman ramah yang bisa menjawab apa saja.
    """
    try:
        system_prompt = (
            "Anda adalah asisten AI bernama Lucy. "
            "Berikan jawaban singkat dalam bahasa Indonesia, maksimal 50 kata, "
            "dengan gaya ramah dan santai. Anda dapat menjawab pertanyaan apa saja, "
            "mulai dari obrolan ringan hingga informasi umum."
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
            return ' '.join(full_response.split()[:50])
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

        await asyncio.to_thread(pygame.mixer.music.load, audio_file)
        await asyncio.to_thread(pygame.mixer.music.play)

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
    welcome_msg = "Halo, saya Lucy AI! Senang bisa ngobrol dengan kalian. Tanyakan apa saja ya!"
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
    await comment_queue.put((username, comment_text))

# ==========================
# 10) Proses Antrean Komentar Satu-per-Satu
# ==========================
async def process_comment_queue():
    """
    Loop tak terhingga: 
    1) ambil satu komentar dari antrean 
    2) ambil respons dari chat_with_agent 
    3) lakukan TTS → putar audio
    4) update last_comment_time
    """
    print("🚀 Memulai pemrosesan antrean komentar...")
    while True:
        try:
            username, comment_text = await comment_queue.get()

            print(f"[DEBUG] Sedang memproses komentar: {username} → “{comment_text}”")

            jawaban = await chat_with_agent(f"{username} menanyakan: {comment_text}")
            print(f"🤖 Lucy: {jawaban}")

            await text_to_speech_and_play(jawaban)

            global last_comment_time
            last_comment_time = time.time()

            comment_queue.task_done()

        except Exception as e:
            print(f"❌ Error dalam process_comment_queue: {e}")
            await asyncio.sleep(1)

# ==========================
# 11) Fungsi keep_alive (aktif)
# ==========================
async def keep_alive():
    """
    Jika 120 detik berlalu sejak komentar terakhir 
    dan antrean kosong, Lucy akan kembali memperkenalkan diri.
    """
    global last_comment_time
    # Inisialisasi last_comment_time jika belum ada
    if last_comment_time is None:
        last_comment_time = time.time()

    while True:
        try:
            now = time.time()
            # Cek: jika 120 detik berlalu, dan antrean komentar kosong
            if (now - last_comment_time) > 120 and comment_queue.empty():
                intro_msg = "Hai lagi! Saya Lucy AI, teman ngobrol kalian. Ada yang mau ditanyakan atau curhat?"
                print(f"⏰ 2 menit tanpa komentar → {intro_msg}")
                await text_to_speech_and_play(intro_msg)
                last_comment_time = time.time()

            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error dalam keep_alive: {e}")
            await asyncio.sleep(5)

# ==========================
# 12) Fungsi connection_monitor
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
# 13) Fungsi test_tiktok_connection
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
# 14) Fungsi test_agent_connection
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
# 15) Fungsi test_elevenlabs_connection
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
# 16) Fungsi main
# ==========================
async def main():
    print("=== Lucy AI Assistant (Sosial) untuk TikTok Live ===")
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
    asyncio.create_task(tiktok_client.connect())

    # Beri jeda singkat supaya on_connect bisa dipicu dulu
    await asyncio.sleep(2)

    print("\n✅ Semua sistem siap! Mulai monitoring komentar…")
    print("💬 Menunggu komentar dari viewers…")

    # Jalankan tiga task paralel:
    #  - process_comment_queue()   (memproses komentar satu per satu)
    #  - keep_alive()              (Lucy tetap on & perkenalan diri setiap 2 menit tanpa komentar)
    #  - connection_monitor()      (cek koneksi tiap 30 detik & reconnect jika perlu)
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
