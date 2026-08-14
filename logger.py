import json
import os


def log(msg, path='logs/conversation_log.json'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        json.dump(msg.__dict__, f)
        f.write('\n')
