import os
import asyncio
import random
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# =====================================================================
# 🛠️ 1. KEEPALIVE SERVER (CHỐNG SẬP/NGỦ ĐÔNG TRÊN RENDER FREE)
# =====================================================================
app = Flask('')

@app.route('/')
def home():
    return "Bot Deep Scan đang chạy ổn định 24/7 trên Render Free!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
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
    print(f"🔍 [DEEP SCAN] Bắt đầu quét xuyên lịch sử {len(TARGET_CHANNELS)} kênh...")

    temp_msg_list = []
    TARGET_PER_CHANNEL = 50   # Số tin nhắn chưa thả đủ cần thu thập trên mỗi kênh
    MAX_LOOKBACK = 1000       # Giới hạn lội tối đa 1000 tin để tránh cào quá nhiều bị Discord quét

    for cid in TARGET_CHANNELS:
        channel = bot.get_channel(cid)
        if not channel: continue

        channel_gathered = 0
        total_scanned = 0
        oldest_msg_id = None
        
        print(f"📖 Đang quét kênh: {cid}...")

        while channel_gathered < TARGET_PER_CHANNEL and total_scanned < MAX_LOOKBACK:
            args = {"limit": 100}
            if oldest_msg_id:
                args["before"] = discord.Object(id=oldest_msg_id)

            history_chunk = []
            try:
                async for msg in channel.history(**args):
                    history_chunk.append(msg)
            except Exception as e:
                print(f"❌ Lỗi lịch sử kênh {cid}: {e}")
                break

            if not history_chunk:
                break  # Đã chạm đáy kênh chat

            oldest_msg_id = history_chunk[-1].id
            total_scanned += len(history_chunk)

            for msg in history_chunk:
                if msg.reactions:
                    # Kiểm tra xem tài khoản của bạn đã react chưa
                    my_reactions = [str(r.emoji) for r in msg.reactions if r.me]
                    missing_reactions = [r for r in msg.reactions if str(r.emoji) not in my_reactions]
                    
                    # Nếu phát hiện tin nhắn có emoji và bạn chưa thả đủ -> Hốt luôn
                    if missing_reactions:
                        temp_msg_list.append(msg)
                        channel_gathered += 1
                        if channel_gathered >= TARGET_PER_CHANNEL:
                            break
                            
        print(f"   -> Đã duyệt qua {total_scanned} tin, lấy được {channel_gathered} tin chưa thả đủ.")

    print(f"🔄 Thu hoạch tổng cộng {len(temp_msg_list)} tin nhắn. Đang trộn ngẫu nhiên...")
    random.shuffle(temp_msg_list)

    for msg in temp_msg_list:
        await reaction_queue.put(msg)

    is_cleaning = False
    print(f"🏁 Đã phân bổ vào hàng đợi xử lý ngầm!")

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
