import io
import os
import shlex
import tarfile
import tempfile
import time
import uuid

import paramiko


def _load_private_key(pem: str):
    """Keys stored on Vps rows aren't always RSA (e.g. ed25519 from ssh-keygen/PuTTYgen),
    so try each key type paramiko supports instead of assuming RSA."""
    last_exc = None
    key_classes = (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey)
    key_classes += (paramiko.DSSKey,) if hasattr(paramiko, "DSSKey") else ()
    for key_cls in key_classes:
        try:
            return key_cls.from_private_key(io.StringIO(pem))
        except paramiko.SSHException as exc:
            last_exc = exc
    raise last_exc


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
                    pkey = _load_private_key(self.private_key_pem)
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
        """Packs local_dir into one tar and extracts it remotely, instead of one SFTP
        round-trip per file plus one `mkdir` per subdirectory — a funnel with a couple
        thousand files took hours over a high-latency link that way, since each small
        file's open/write/close is a separate serialized round-trip."""
        self.run(f"mkdir -p {shlex.quote(remote_dir)}")
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar")
        os.close(tmp_fd)
        try:
            with tarfile.open(tmp_path, "w") as tar:
                tar.add(local_dir, arcname=".")
            remote_tmp = f"/tmp/funnel-upload-{uuid.uuid4().hex}.tar"
            sftp = self._open_sftp()
            try:
                sftp.put(tmp_path, remote_tmp)
            finally:
                sftp.close()
            self.run(f"tar -xf {shlex.quote(remote_tmp)} -C {shlex.quote(remote_dir)} && rm -f {shlex.quote(remote_tmp)}")
        finally:
            os.remove(tmp_path)

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
