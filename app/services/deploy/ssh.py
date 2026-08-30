import io
import os
import time

import paramiko


class SSHSession:
    """Thin wrapper around paramiko for exec + SFTP upload, with retrying connect
    (a freshly provisioned VPS may take a minute to accept SSH connections)."""

    def __init__(self, host: str, user: str, private_key_pem: str = "", password: str = "", port: int = 22, timeout: int = 20):
        self.host = host
        self.user = user
        self.private_key_pem = private_key_pem
        self.password = password
        self.port = port
        self.timeout = timeout
        self._client = None

    def connect(self, retries: int = 15, delay: int = 8):
        last_exc = None
        for _ in range(retries):
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if self.private_key_pem:
                    pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.private_key_pem))
                    client.connect(self.host, port=self.port, username=self.user, pkey=pkey, timeout=self.timeout)
                else:
                    client.connect(self.host, port=self.port, username=self.user, password=self.password, timeout=self.timeout)
                self._client = client
                return
            except paramiko.AuthenticationException as exc:
                raise RuntimeError(f"Falha de autenticação SSH em {self.host}: usuário/senha (ou chave) incorretos.") from exc
            except Exception as exc:
                last_exc = exc
                time.sleep(delay)
        raise RuntimeError(f"Não foi possível conectar via SSH em {self.host}: {last_exc}")

    def run(self, command: str, timeout: int = 180) -> str:
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if exit_code != 0:
            raise RuntimeError(f"Comando falhou ({exit_code}): {command}\n{(err or out).strip()}")
        return out

    def _open_sftp(self, stall_timeout: int = 600):
        """Opens SFTP with a stall timeout — without it, a stalled transfer (dropped
        connection, unresponsive VPS) blocks the deploy thread forever with no exception,
        leaving the deployment stuck mid-status with nothing to mark it as failed."""
        sftp = self._client.open_sftp()
        sftp.get_channel().settimeout(stall_timeout)
        return sftp

    def write_file(self, remote_path: str, content: str):
        sftp = self._open_sftp()
        with sftp.open(remote_path, "w") as f:
            f.write(content)
        sftp.close()

    def upload_dir(self, local_dir: str, remote_dir: str):
        sftp = self._open_sftp()
        self.run(f"mkdir -p {remote_dir}")
        for root, dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir)
            remote_root = remote_dir if rel == "." else f"{remote_dir}/{rel.replace(os.sep, '/')}"
            if rel != ".":
                self.run(f"mkdir -p {remote_root}")
            for fname in files:
                sftp.put(os.path.join(root, fname), f"{remote_root}/{fname}")
        sftp.close()

    def close(self):
        if self._client:
            self._client.close()


class MockSSHSession:
    """No-op SSH session used when vps.provider == 'mock' — lets the deploy flow
    be exercised end-to-end locally without a real server."""

    def __init__(self, host="", user="", private_key_pem="", timeout=20):
        pass

    def connect(self, retries=1, delay=0):
        pass

    def run(self, command: str, timeout: int = 180) -> str:
        return ""

    def write_file(self, remote_path: str, content: str):
        pass

    def upload_dir(self, local_dir: str, remote_dir: str):
        pass

    def close(self):
        pass


def get_ssh_session(vps) -> "SSHSession | MockSSHSession":
    if vps.provider == "mock":
        return MockSSHSession()
    return SSHSession(
        host=vps.ip_address,
        user=vps.ssh_user or "root",
        private_key_pem=vps.get_ssh_key(),
        password=vps.get_ssh_password(),
        port=vps.ssh_port or 22,
    )
