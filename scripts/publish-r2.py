#!/usr/bin/env python3
"""Mirror a tested release, verify public downloads, then advance latest.json."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from upgrade import fetch, unpack, version

def publish(client, bucket, public_url, release, directory):
    release = version(release)
    parsed = urlsplit(public_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('R2_PUBLIC_URL must be a public HTTPS base URL.')
    prefix = 'mofis-deploy/'
    archive = 'mofis-deploy-' + release + '.zip'
    data = (directory/archive).read_bytes()
    sums = (directory/'SHA256SUMS').read_bytes()
    unpack(data, sums.decode(), release)
    for name, body, mime in [(archive, data, 'application/zip'), ('SHA256SUMS', sums, 'text/plain; charset=utf-8')]:
        client.put_object(Bucket=bucket, Key=prefix+release+'/'+name, Body=body,
                          ContentType=mime, CacheControl='public, max-age=31536000, immutable')
    base = public_url.rstrip('/') + '/' + prefix + release + '/'
    downloaded = fetch(base+archive)
    downloaded_sums = fetch(base+'SHA256SUMS')
    if downloaded != data or downloaded_sums != sums:
        raise ValueError('Public R2 downloads do not match this release; latest was not updated.')
    unpack(downloaded, downloaded_sums.decode(), release)
    try:
        current = json.loads(client.get_object(Bucket=bucket, Key=prefix+'latest.json')['Body'].read())
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') not in ['NoSuchKey', '404']:
            raise
        current = None
    if current and tuple(map(int, version(current['version']).split('.'))) > tuple(map(int, release.split('.'))):
        print('Older release mirrored; latest.json retained.')
        return
    client.put_object(Bucket=bucket, Key=prefix+'latest.json', Body=(json.dumps({'version': release})+'\n').encode(),
                      ContentType='application/json', CacheControl='no-store, max-age=0')
    print('Published and verified: ' + base + archive)

def main():
    import boto3
    account = os.environ['R2_ACCOUNT_ID']
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account):
        raise ValueError('Invalid R2_ACCOUNT_ID.')
    client = boto3.client('s3', endpoint_url='https://'+account+'.r2.cloudflarestorage.com', region_name='auto',
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'])
    publish(client, os.environ['R2_BUCKET'], os.environ['R2_PUBLIC_URL'], Path('VERSION').read_text().strip(), Path('dist'))

if __name__ == '__main__':
    main()
