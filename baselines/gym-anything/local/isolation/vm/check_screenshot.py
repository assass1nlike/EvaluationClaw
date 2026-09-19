"""Exercise the configured official screenshot tool inside a running generation VM."""
import json
import os
from pathlib import Path
import random
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
from PIL import Image, ImageDraw
from local.isolation.vm import screenshot_mcp


def main():
    random.seed(42)
    job=Path('/home/ga/job')
    os.environ.update(json.loads((job/'environment.json').read_text()))
    api=dotenv_values(ROOT/'local/.env')
    os.environ.update(SCREENSHOT_QUERY_PROVIDER='openai',SCREENSHOT_QUERY_MODEL=api['DEEPSEEK_MODEL'],
                      SCREENSHOT_QUERY_BASE_URL=api['DEEPSEEK_BASE_URL'],SCREENSHOT_QUERY_API_KEY=api['DEEPSEEK_API_KEY'],
                      GYM_SCREENSHOT_AUDIT=str(job/'screenshot-smoke-api.jsonl'))
    screenshot=job/'screenshot-smoke.png'
    im=Image.new('RGB',(1280,720),'white');draw=ImageDraw.Draw(im)
    draw.rectangle((100,100,300,300),fill='red')
    draw.ellipse((800,100,1000,300),fill='blue')
    im.save(screenshot)
    with patch.object(screenshot_mcp.official.openai,'OpenAI',screenshot_mcp.configured_client):
        answer=screenshot_mcp.official.visual_grounding('Describe the two colored shapes, their colors, left/right positions and approximate center coordinates.',str(screenshot))
    (job/'screenshot-smoke.json').write_text(json.dumps({'seed':42,'model':api['DEEPSEEK_MODEL'],'response':answer},indent=2)+'\n')


if __name__=='__main__':main()
