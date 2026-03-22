import sys

with open('old_str_utf8.py', 'r', encoding='utf-8') as f:
    old_lines = f.readlines()
    
# lines 2047 to 2344 are indexes 2046 to 2344
missing_code = old_lines[2046:2344]

with open('ui/pages/zapret2/strategy_detail_page.py', 'r', encoding='utf-8') as f:
    new_lines = f.readlines()
    
for i, line in enumerate(new_lines):
    if 'def _refresh_args_editor_state(self):' in line:
        new_lines = new_lines[:i] + missing_code + ['\n'] + new_lines[i:]
        break
        
with open('ui/pages/zapret2/strategy_detail_page.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
    
print('Restored successfully')
