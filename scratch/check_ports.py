import socket

def is_port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except:
        return False
    finally:
        s.close()

print("Port 8000 open:", is_port_open(8000))
print("Port 5173 open:", is_port_open(5173))
