import time
import zlib
from urllib.parse import unquote

import requests

# Client that makes periodic requests to the root domain for a random file and stores it locally.
def client():
    print("Starting client...")
    increment = 0
    while True:
        res = requests.get("http://127.0.0.1:5001")
        if res.status_code == 200: # If OK...
            if res.headers.get("Content-Disposition"): # Holds the filename argument, which we use to extract the checksum
                cd = res.headers.get("Content-Disposition")
                filename = cd.split('filename=')[-1] # Isolate and strip the filename of all formatting.
                checksum = int(unquote(filename).strip('"'))

            # Write the received content.
            with open(f'received/recfile{increment}.txt', 'wb') as file:
                file.write(res.content)

            # Check the received content with the extracted checksum
            with open(f'received/recfile{increment}.txt', 'rb') as file:
                data = 0
                while True:
                    stream = file.read(2048)
                    if not stream:
                        break
                    data = zlib.crc32(stream, data)
                out = data
            # If our checksum does not match, indicate so
            if out != checksum:
                print("Malformed checksum.")
            else:
                print(f"Checksum OK. File {increment+1} written.")

            # Set our increment, sleep & proceed.
            increment += 1
            time.sleep(2)

if __name__ == "__main__":
    client()