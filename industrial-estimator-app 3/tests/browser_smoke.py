"""Local Chromium UI smoke test against a running server.
Start with: uvicorn backend.app:app --host 127.0.0.1 --port 8765
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

BASE=os.environ.get('BROWSER_URL','http://127.0.0.1:8765')
OUT=Path(__file__).resolve().parents[1]/'screenshots'
OUT.mkdir(exist_ok=True)

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
        console_errors=[]
        page.on('pageerror',lambda err:console_errors.append(str(err)))
        await page.goto(BASE,wait_until='networkidle')
        await page.screenshot(path=str(OUT/'01-login.png'),full_page=True)
        assert await page.locator('h2').inner_text()=='Welcome back'
        await page.locator('input[name=username]').fill('demo')
        await page.locator('input[name=password]').fill('demo-pass-123')
        await page.get_by_role('button',name='Sign in').click()
        await page.get_by_text('Good to see you again').wait_for(timeout=15000)
        await page.screenshot(path=str(OUT/'02-dashboard.png'),full_page=True)
        await page.get_by_role('button',name='Quotations',exact=True).click()
        await page.get_by_text('Quotation register').wait_for()
        await page.screenshot(path=str(OUT/'03-projects.png'),full_page=True)
        await page.get_by_role('button',name='Open →').first.click()
        await page.get_by_text('Quotation progress').wait_for()
        await page.screenshot(path=str(OUT/'04-project-overview.png'),full_page=True)
        await page.get_by_role('button',name='BOM & materials').click()
        await page.get_by_text('Materials & assemblies').wait_for()
        await page.screenshot(path=str(OUT/'05-bom.png'),full_page=True)
        await page.get_by_role('button',name='Cost & approvals').click()
        await page.get_by_text('Cost breakdown').wait_for()
        await page.screenshot(path=str(OUT/'06-review.png'),full_page=True)
        await page.get_by_role('button',name='Open provisional PDF').click()
        await page.locator('iframe.pdf-frame').wait_for()
        await page.screenshot(path=str(OUT/'07-pdf-preview.png'),full_page=True)
        await page.get_by_role('button',name='×').last.click()
        await page.get_by_role('button',name='Price book').click()
        await page.get_by_text('Item catalogue').wait_for()
        await page.screenshot(path=str(OUT/'08-prices.png'),full_page=True)
        await page.get_by_role('button',name='Product library').click()
        await page.get_by_text('General made-to-order fabrication').wait_for()
        await page.screenshot(path=str(OUT/'09-configs.png'),full_page=True)
        assert not console_errors,console_errors
        print('UI smoke test passed. 9 screenshots, no JS page errors.')
        await browser.close()

if __name__=='__main__':asyncio.run(main())
