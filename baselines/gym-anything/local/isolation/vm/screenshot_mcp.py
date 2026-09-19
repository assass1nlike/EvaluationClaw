"""Configure the official screenshot MCP for DeepSeek thinking/high."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from extras.research.software_as_env.creation_audit.mcp import screenshot_query_mcp as official

OriginalClient = official.openai.OpenAI


def configured_client(*args, **kwargs):
    client = OriginalClient(*args, **kwargs)
    original = client.chat.completions.create

    def create(**params):
        params.update(reasoning_effort='high', extra_body={'thinking': {'type': 'enabled'}})
        row = {'time': time.time(), 'model': params['model'], 'thinking': 'enabled',
               'reasoning_effort': 'high', 'max_tokens': params.get('max_tokens')}
        try:
            response = original(**params)
            msg = response.choices[0].message
            row.update(success=True, finish_reason=response.choices[0].finish_reason,
                       content_characters=len(msg.content or ''),
                       reasoning_characters=len(getattr(msg,'reasoning_content',None) or ''),
                       usage=response.usage.model_dump() if response.usage else None)
            return response
        except Exception as error:
            row.update(success=False,error_type=type(error).__name__,status=getattr(error,'status_code',None))
            raise
        finally:
            with open(os.environ['GYM_SCREENSHOT_AUDIT'],'a') as f:
                f.write(json.dumps(row)+'\n')

    client.chat.completions.create = create
    return client


if __name__ == '__main__':
    with patch.object(official.openai, 'OpenAI', configured_client):
        official.mcp.run()
