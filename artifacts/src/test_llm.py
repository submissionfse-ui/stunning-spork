"""Read the AB regex from file and send it to Opus via SDK."""
import os
from dotenv import load_dotenv
load_dotenv()

import anthropic

# Read the first regex from the AB output file
with open('/tmp/ab_output.txt') as f:
    lines = f.readlines()

# Get the raw regex from the summary section (line 21 in the file)
# "      Raw regex: ..."
for line in lines:
    if line.strip().startswith('Raw regex:'):
        regex = line.strip().split('Raw regex:', 1)[1].strip()
        break

with open('/tmp/llm_regex_test.txt', 'w') as out:
    out.write(f'Regex length: {len(regex)} chars\n')
    out.write(f'First 100 chars: {regex[:100]}\n\n')

    try:
        client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
        out.write('Calling Opus 4.6...\n')
        out.flush()

        resp = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=2048,
            messages=[{
                'role': 'user',
                'content': f"""This regex represents AWS resources allowed by actions: s3:*, cloudwatch:*, ec2:*

Raw regex from DFA:
{regex}

Simplify it and give 3 example resource ARNs.
Reply EXACTLY like:
SIMPLIFIED: <regex>
EXAMPLE: <arn>
EXAMPLE: <arn>
EXAMPLE: <arn>"""
            }]
        )
        out.write(f'Response:\n{resp.content[0].text}\n')
        out.write(f'Input tokens: {resp.usage.input_tokens}\n')
        out.write(f'Output tokens: {resp.usage.output_tokens}\n')
    except Exception as e:
        out.write(f'ERROR: {type(e).__name__}: {e}\n')
