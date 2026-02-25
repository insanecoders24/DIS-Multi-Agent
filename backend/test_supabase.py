import os
from dotenv import load_dotenv
load_dotenv(override=True)
from supabase import create_client, Client
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')
supabase = create_client(url, key)
print('Supabase initialized.')
try:
    res = supabase.storage.get_bucket('documents')
    print('bucket documents:', res)
except Exception as e:
    print('bucket documents Error:', e)
try:
    with open('test.txt', 'wb') as f:
        f.write(b'hello')
    with open('test.txt', 'rb') as f:
        res = supabase.storage.from_('documents').upload('test.txt', f, file_options={'content-type': 'text/plain'})
    print('upload res:', res)
except Exception as e:
    print('upload Error:', type(e), e)
try:
    res = supabase.storage.from_('page-images').create_signed_url('somepath', 60)
    print('signed url:', res)
except Exception as e:
    print('signed url Error:', type(e), e)
