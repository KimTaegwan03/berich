# bot_runner.py
import asyncio
import traceback

from main import trading_bot_loop, crawler_loop

import dotenv
dotenv.load_dotenv()


async def run_forever():
    """
    crawler_loop / trading_bot_loop 중 하나라도 예외로 죽으면
    에러 로그 찍고 둘 다 취소 후 잠깐 쉬었다가 다시 시작.
    """
    while True:
        print("🟢 [Runner] 봇 프로세스 시작")
        tasks = [
            asyncio.create_task(crawler_loop(), name="crawler_loop"),
            asyncio.create_task(trading_bot_loop(True), name="trading_bot_loop"),
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        # 어떤 태스크가 죽었는지/왜 죽었는지 출력
        for t in done:
            exc = t.exception()
            if exc:
                print(f"🔴 [Runner] Task crashed: {t.get_name()}")
                traceback.print_exception(type(exc), exc, exc.__traceback__)

        # 나머지 태스크 취소
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        print("🟡 [Runner] 5초 후 재시작...")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_forever())
