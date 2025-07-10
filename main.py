import os
import pandas as pd
import asyncio
import aiohttp
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")

# Google cho phép tối đa 4 requests/giây trên 1 API key miễn phí
GOOGLE_RPS_LIMIT = 4         # requests per second (tối đa)
MAX_CONCURRENCY = 20         # bảo vệ server tránh quá tải, và để mở rộng nếu nâng quota

def get_concurrent_limit(num_links):
    # Chỉ dùng đủ số luồng cần thiết, không vượt Google quota, và không vượt MAX_CONCURRENCY
    return min(GOOGLE_RPS_LIMIT, num_links, MAX_CONCURRENCY)

async def get_performance_score_async(session, url, semaphore):
    api_url = (
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        f"?url={url}&strategy=mobile&key={PAGESPEED_API_KEY}"
    )
    async with semaphore:
        try:
            async with session.get(api_url, timeout=30) as r:
                data = await r.json()
                if 'error' in data:
                    return url, None, f"error: {data['error'].get('message', '')}"
                if "lighthouseResult" in data and \
                   "categories" in data["lighthouseResult"] and \
                   "performance" in data["lighthouseResult"]["categories"]:
                    score = data["lighthouseResult"]["categories"]["performance"]["score"]
                    if score is not None:
                        score_int = int(round(score * 100))
                        return url, score_int, "ok" if score_int >= 80 else "not ok"
                return url, None, "no performance data"
        except Exception as e:
            return url, None, f"error: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gửi file Excel (.xlsx) chứa danh sách URL (cột đầu tiên) vào đây.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("Không nhận được file.")
        return
    file_name = update.message.document.file_name
    if not file_name.endswith(".xlsx"):
        await update.message.reply_text("Chỉ chấp nhận file .xlsx.")
        return
    file = await update.message.document.get_file()
    file_path = f"/tmp/input_{update.message.document.file_id}.xlsx"
    await file.download_to_drive(file_path)
    try:
        df = pd.read_excel(file_path)
        if df.shape[1] < 1:
            await update.message.reply_text("File Excel không có cột nào.")
            return
        urls = df.iloc[:, 0].dropna().tolist()
        if not urls:
            await update.message.reply_text("Không tìm thấy URL nào trong file.")
            return

        await update.message.reply_text(f"Đã nhận file. Tổng số link sẽ xử lý: {len(urls)}")
        concurrent_limit = get_concurrent_limit(len(urls))
        status_msg = await update.message.reply_text(
            f"Bắt đầu kiểm tra link (tối đa {concurrent_limit} luồng song song, tối đa {GOOGLE_RPS_LIMIT} request/giây)..."
        )

        # Xử lý song song nhưng không vượt quá quota Google (thực tế vẫn nên delay nhẹ tránh burst)
        results = []
        semaphore = asyncio.Semaphore(concurrent_limit)
        async with aiohttp.ClientSession() as session:
            tasks = [get_performance_score_async(session, url, semaphore) for url in urls]
            for idx, coro in enumerate(asyncio.as_completed(tasks), 1):
                url, perf, status = await coro
                results.append({
                    "STT": idx,
                    "URL": url,
                    "Performance": perf if perf is not None else "N/A",
                    "Status": status,
                })
                # Log sau mỗi 10 link hoặc cuối cùng
                if idx % 10 == 0 or idx == len(urls):
                    await status_msg.edit_text(f"Đã xử lý {idx}/{len(urls)} link...")

        result_df = pd.DataFrame(results)
        output_path = f"/tmp/result_{update.message.document.file_id}.xlsx"
        result_df.to_excel(output_path, index=False)
        await update.message.reply_document(InputFile(output_path, filename="result.xlsx"))
        await update.message.reply_text("Đã hoàn tất. Đã gửi file kết quả.")
    except Exception as e:
        await update.message.reply_text(f"Lỗi xử lý file: {e}")
    finally:
        try: os.remove(file_path)
        except: pass

def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Lỗi: Chưa thiết lập biến môi trường TELEGRAM_BOT_TOKEN")
        exit(1)
    if not PAGESPEED_API_KEY:
        print("Lỗi: Chưa thiết lập biến môi trường PAGESPEED_API_KEY")
        exit(1)
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot đã sẵn sàng.")
    app.run_polling()

if __name__ == "__main__":
    main()
