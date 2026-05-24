import os
import asyncio
import random
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# =====================================================================
# 🛠️ 1. KEEPALIVE SERVER (ĐÃ TỐI ƯU HÓA KHÔNG GÂY NGHẼN CHO DISCORD.PY)
# =====================================================================
app = Flask('')

# Tắt log hiển thị của Flask trên bảng Console để đỡ rối mắt và nhẹ máy
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "OK", 200  # Trả về kết quả ngắn gọn nhất để giải phóng luồng ngay lập tức

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    # Chạy Flask ở chế độ đơn luồng tối giản nhất, không tải lại (threaded=False, use_reloader=False)
    app.run(host='0.0.0.0', port=port, threaded=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True  # Chạy ngầm hoàn toàn tách biệt với bot
    t.start()

keep_alive()

# =====================================================================
# ⚙️ 2. CẤU HÌNH ĐƯỜNG DẪN FILE (CHỈ ĐỌC DANH SÁCH KÊNH TỪ GITHUB)
# =====================================================================
TOKEN = os.getenv("DISCORD_TOKEN")
prefix = "!"
# Trên Render Free, ta đọc danh sách kênh trực tiếp từ file bạn push lên GitHub
channels_file = "backup_channels.txt"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=prefix,
                   help_command=None,
                   intents=intents,
                   self_bot=True)

TOTAL_REACT_LIMIT = 15000  # Hạn mức react tối đa bạn muốn
current_total_reacts = 0   # Reset về 0 mỗi khi khởi động lại (hoặc chỉnh bằng lệnh !total)
auto_react_enabled = True
reaction_queue = asyncio.Queue()
is_cleaning = False

def _sync_load_channels():
    if not os.path.exists(channels_file):
        print(f"❌ Không tìm thấy file {channels_file} ở thư mục gốc!")
        return []
    with open(channels_file, "r", encoding="utf-8") as f:
        return [int(line.strip()) for line in f if line.strip() and not line.startswith("#")]

TARGET_CHANNELS = _sync_load_channels()

# --- HÀM REACT CỐT LÕI ---
async def smart_react(msg, channel_id):
    global current_total_reacts

    if not auto_react_enabled or current_total_reacts >= TOTAL_REACT_LIMIT:
        return

    my_reactions = [str(r.emoji) for r in msg.reactions if r.me]
    missing_reactions = [r for r in msg.reactions if str(r.emoji) not in my_reactions]

    if not missing_reactions: 
        return

    num_to_react = min(len(missing_reactions), TOTAL_REACT_LIMIT - current_total_reacts)
    reactions_to_add = random.sample(missing_reactions, num_to_react)

    for reaction in reactions_to_add:
        try:
            await msg.add_reaction(reaction.emoji)
            current_total_reacts += 1
            print(f"[{channel_id}] ✨ Đã thả: {current_total_reacts}/{TOTAL_REACT_LIMIT}")
            await asyncio.sleep(random.uniform(0.8, 1.4))
        except Exception as e:
            print(f"⚠️ Lỗi thả emoji tại kênh {channel_id}: {e}")
            break

# --- WORKER VÀ EVENT ---
async def reaction_worker():
    while True:
        try:
            msg = await reaction_queue.get()
            while is_cleaning:
                await asyncio.sleep(1)

            if auto_react_enabled and current_total_reacts < TOTAL_REACT_LIMIT:
                await smart_react(msg, msg.channel.id)
                await asyncio.sleep(random.uniform(0.8, 1.5))
        except Exception as e:
            print(f"❌ Lỗi Worker ngầm: {e}")
        finally:
            reaction_queue.task_done()

@bot.event
async def on_message(message):
    if not auto_react_enabled or message.channel.id not in TARGET_CHANNELS:
        await bot.process_commands(message)
        return

    async def wait_and_push(m):
        await asyncio.sleep(random.uniform(5, 8))
        try:
            refreshed_msg = await m.channel.fetch_message(m.id)
            if refreshed_msg.reactions:
                await reaction_queue.put(refreshed_msg)
        except:
            pass

    bot.loop.create_task(wait_and_push(message))
    await bot.process_commands(message)

# =====================================================================
# 🧭 3. THUẬT TOÁN DEEP SCAN: LỘI NGƯỢC DÒNG TỰ ĐỘNG KHÔNG CẦN CHECKPOINT
# =====================================================================
@bot.command(aliases=["clean"])
async def follow_old(ctx):
    global is_cleaning
    try: await ctx.message.delete()
    except: pass
    if not auto_react_enabled: return

    is_cleaning = True
    print(f"🧹 [HỆ THỐNG] Bắt đầu quét cuốn chiếu và tối ưu chống Rate Limit...")

    TARGET_PER_CHANNEL = 40   # Số tin nhắn cần lấy mỗi kênh
    MAX_LOOKBACK = 600        # Giới hạn lội ngược dòng để an toàn RAM
    
    # Rổ lớn để gom tối đa tin nhắn của TẤT CẢ các kênh trước khi trộn tổng thể
    global_temp_list = []

    # Đảo thứ tự quét các kênh để tăng tính ngẫu nhiên
    shuffled_channels = TARGET_CHANNELS.copy()
    random.shuffle(shuffled_channels)

    for cid in shuffled_channels:
        if current_total_reacts >= TOTAL_REACT_LIMIT:
            break

        channel = bot.get_channel(cid)
        if not channel: continue

        channel_gathered = 0
        total_scanned = 0
        oldest_msg_id = None

        while channel_gathered < TARGET_PER_CHANNEL and total_scanned < MAX_LOOKBACK:
            args = {"limit": 50}  # Chia nhỏ để Render Free không bị nghẹn
            if oldest_msg_id:
                args["before"] = discord.Object(id=oldest_msg_id)

            history_chunk = []
            try:
                async for msg in channel.history(**args):
                    history_chunk.append(msg)
            except Exception as e:
                print(f"❌ Lỗi đọc lịch sử kênh {cid}: {e}")
                break

            if not history_chunk:
                break

            oldest_msg_id = history_chunk[-1].id
            total_scanned += len(history_chunk)

            for msg in history_chunk:
                if msg.reactions:
                    my_reactions = [str(r.emoji) for r in msg.reactions if r.me]
                    missing_reactions = [r for r in msg.reactions if str(r.emoji) not in my_reactions]
                    
                    if missing_reactions:
                        global_temp_list.append(msg) # Đổ chung vào rổ lớn
                        channel_gathered += 1
                        if channel_gathered >= TARGET_PER_CHANNEL:
                            break
            
            del history_chunk # Dọn RAM ngay lập tức

    # 🔥 THUẬT TOÁN CHÍ MẠNG: Trộn phẳng toàn bộ rổ lớn để đảm bảo 
    # các tin nhắn của cùng một kênh không bao giờ nằm cạnh nhau!
    if global_temp_list:
        print(f"🔄 Tổng gom được {len(global_temp_list)} tin nhắn. Tiến hành trộn phẳng toàn bộ hệ thống...")
        random.shuffle(global_temp_list)
        random.shuffle(global_temp_list) # Trộn hẳn 2 lần cho chắc chắn

        # Đẩy đống dữ liệu đã xáo cực đều này vào hàng đợi cho Worker chạy ngầm
        for msg in global_temp_list:
            await reaction_queue.put(msg)
        
        print(f"📦 Đã phân bổ {len(global_temp_list)} tin nhắn vào hàng đợi. Giải phóng rổ tạm...")
        del global_temp_list # Xóa sạch rổ lớn để trả lại RAM trống cho Render

    is_cleaning = False
    print(f"🏁 [SẴN SÀNG] Worker bắt đầu thả xen kẽ các kênh, không lo dính Rate Limit!")

@bot.command()
async def total(ctx, num: int):
    global TOTAL_REACT_LIMIT
    TOTAL_REACT_LIMIT = num
    try: await ctx.message.delete()
    except: pass
    print(f"♻️ Hạn mức mới: {num}")

@bot.command()
async def reload(ctx):
    global TARGET_CHANNELS
    try:
        TARGET_CHANNELS = await asyncio.to_thread(_sync_load_channels)
        try: await ctx.message.delete()
        except: pass
        print(f"🔄 ĐÃ CẬP NHẬT: Hiện có {len(TARGET_CHANNELS)} kênh.")
    except Exception as e:
        print(f"❌ Lỗi: {e}")

@bot.command()
async def start(ctx):
    global auto_react_enabled
    auto_react_enabled = True
    try: await ctx.message.delete()
    except: pass
    print("▶️ BẬT AUTO REACT")

@bot.command()
async def stop(ctx):
    global auto_react_enabled
    auto_react_enabled = False
    try: await ctx.message.delete()
    except: pass
    print("⛔ DỪNG AUTO REACT")

@bot.event
async def on_ready():
    bot.loop.create_task(reaction_worker())
    print(f"✅ Bot Online (Gói Free Render) | Tiến độ: {current_total_reacts}/{TOTAL_REACT_LIMIT} | Kênh: {len(TARGET_CHANNELS)}")

bot.run(TOKEN, bot=False)
