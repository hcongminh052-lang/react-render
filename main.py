import json
import os
import asyncio
import random
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# =====================================================================
# 🛠️ 1. KEEPALIVE SERVER (BẮT BUỘC PHẢI CÓ TRÊN RENDER ĐỂ CHỐNG SẬP/NGỦ)
# =====================================================================
app = Flask('')

@app.route('/')
def home():
    return "Bot đang chạy ổn định 24/7 trên Render!"

def run_flask():
    # Render yêu cầu nhận cổng PORT thông qua biến môi trường của hệ thống
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# =====================================================================
# ⚙️ 2. CẤU HÌNH ĐƯỜNG DẪN ĐÃ ĐỔI SANG RENDER DISK (/data/)
# =====================================================================
TOKEN = os.getenv("DISCORD_TOKEN")
prefix = "!"
checkpoint_file = "/data/checkpoints_multi.json"
channels_file = "/data/channels.txt"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=prefix,
                   help_command=None,
                   intents=intents,
                   self_bot=True)

TOTAL_REACT_LIMIT = 15000
auto_react_enabled = True
reaction_queue = asyncio.Queue()
is_cleaning = False

# --- HÀM QUẢN LÝ DỮ LIỆU BẤT ĐỒNG BỘ ---
def _sync_load_data():
    default_data = {"checkpoints": {}, "stats": {"current_total": 0, "limit": TOTAL_REACT_LIMIT}}
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "stats" not in data: data["stats"] = default_data["stats"]
                if "checkpoints" not in data: data["checkpoints"] = {}
                return data
        except:
            return default_data
    return default_data

def _sync_save_data(data):
    # Đảm bảo thư mục /data tồn tại trước khi ghi file
    os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def _sync_load_channels():
    backup_file = "backup_channels.txt"
    
    # Tạo thư mục lưu trữ nếu chưa có
    os.makedirs(os.path.dirname(channels_file), exist_ok=True)
    
    if not os.path.exists(channels_file):
        with open(channels_file, "w", encoding="utf-8") as f: pass

    with open(channels_file, "r", encoding="utf-8") as f:
        channels = [int(line.strip()) for line in f if line.strip() and not line.startswith("#")]

    # Nếu Disk trống, lấy danh sách từ file mồi backup_channels.txt đưa vào Disk
    if not channels and os.path.exists(backup_file):
        print("💡 [RENDER DISK] Phát hiện Disk trống. Đang nạp kênh từ file dự phòng...")
        with open(backup_file, "r", encoding="utf-8") as f_backup:
            backup_content = f_backup.read()
        
        with open(channels_file, "w", encoding="utf-8") as f_volume:
            f_volume.write(backup_content)
            
        channels = [int(line.strip()) for line in backup_content.split("\n") if line.strip() and not line.startswith("#")]

    return channels

async def save_all_data():
    data = {
        "checkpoints": channel_checkpoints,
        "stats": {
            "current_total": current_total_reacts,
            "limit": TOTAL_REACT_LIMIT
        }
    }
    await asyncio.to_thread(_sync_save_data, data)

# Khởi tạo dữ liệu ban đầu
data_store = _sync_load_data()
channel_checkpoints = data_store["checkpoints"]
current_total_reacts = data_store["stats"]["current_total"]
TOTAL_REACT_LIMIT = data_store["stats"]["limit"]
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

    await save_all_data()

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

# --- LỆNH ĐIỀU KHIỂN ---
@bot.command(aliases=["clean"])
async def follow_old(ctx):
    global is_cleaning
    try: await ctx.message.delete()
    except: pass
    if not auto_react_enabled: return

    is_cleaning = True
    print(f"🧹 [HỆ THỐNG] ĐANG TIẾN HÀNH THU THẬP TIN NHẮN TỪ {len(TARGET_CHANNELS)} KÊNH...")

    temp_msg_list = []

    for cid in TARGET_CHANNELS:
        if len(temp_msg_list) >= (TOTAL_REACT_LIMIT - current_total_reacts):
            break

        channel = bot.get_channel(cid)
        if not channel: continue

        last_id = channel_checkpoints.get(str(cid), {}).get("last_id")
        args = {"limit": 150} 
        if last_id: args["before"] = discord.Object(id=int(last_id))

        try:
            async for msg in channel.history(**args):
                if msg.reactions:
                    temp_msg_list.append(msg)
                channel_checkpoints[str(cid)] = {"last_id": str(msg.id)}
        except Exception as e:
            print(f"❌ Lỗi khi quét kênh {cid}: {e}")

    print(f"🔄 Đang trộn ngẫu nhiên {len(temp_msg_list)} tin nhắn...")
    random.shuffle(temp_msg_list)

    for msg in temp_msg_list:
        await reaction_queue.put(msg)

    await save_all_data()
    is_cleaning = False
    print(f"🏁 ĐÃ PHÂN BỔ XONG HÀNG ĐỢI.")

@bot.command()
async def total(ctx, num: int):
    global TOTAL_REACT_LIMIT
    TOTAL_REACT_LIMIT = num
    await save_all_data()
    try: await ctx.message.delete()
    except: pass
    print(f"♻️ Hạn mức mới: {num}")

@bot.command()
async def get_backup(ctx):
    try:
        try: await ctx.message.delete()
        except: pass
        if os.path.exists(checkpoint_file):
            await ctx.send("📦 File checkpoint từ Render Disk:", file=discord.File(checkpoint_file))
        else:
            await ctx.send("❌ Không tìm thấy file checkpoint!")
    except Exception as e:
        print(f"❌ Lỗi: {e}")

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
    await save_all_data()
    try: await ctx.message.delete()
    except: pass
    print("⛔ DỪNG AUTO REACT")

@bot.event
async def on_ready():
    bot.loop.create_task(reaction_worker())
    print(f"✅ Bot Online | Tiến độ: {current_total_reacts}/{TOTAL_REACT_LIMIT} | Kênh: {len(TARGET_CHANNELS)}")

keep_alive()
bot.run(TOKEN, bot=False)
