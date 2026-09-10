from ... import db
from ...models import Deployment

BASE_PORT = 3001
MAX_PORT = 3999


def allocate_port(deployment: Deployment) -> int:
    """Reserves a local port for a Node deployment's process on its VPS.

    Idempotent: a retry of a deployment that already has a port keeps it, since the
    systemd unit and .env on the server may already reference it. The DB row is the
    source of truth (committed immediately) rather than an in-memory set, because
    different DeployBatches run in separate threads (jobs.start_deploy_batch_job) and
    could otherwise race to pick the same port on the same VPS.
    """
    if deployment.app_port:
        return deployment.app_port

    taken = {
        row[0]
        for row in db.session.query(Deployment.app_port)
        .filter(Deployment.vps_id == deployment.vps_id, Deployment.app_port > 0)
        .all()
    }
    for port in range(BASE_PORT, MAX_PORT + 1):
        if port not in taken:
            deployment.app_port = port
            db.session.commit()
            return port

    raise RuntimeError(f"Nenhuma porta livre entre {BASE_PORT} e {MAX_PORT} neste VPS.")


def claim_port(deployment: Deployment, port: int) -> None:
    """Reserves a port the app chose for itself instead of the one it was assigned.

    Refuses when another deployment on the same VPS already holds it: two funnels that
    both hardcode the same port cannot coexist there, and silently pointing this domain's
    nginx at a port owned by another domain would serve the wrong funnel.
    """
    if deployment.app_port == port:
        return

    conflict = Deployment.query.filter(
        Deployment.vps_id == deployment.vps_id,
        Deployment.app_port == port,
        Deployment.id != deployment.id,
    ).first()
    if conflict:
        raise RuntimeError(
            f"A aplicação subiu na porta {port}, que já está reservada para outro funil "
            f"neste VPS (deployment #{conflict.id}). Para dividir o servidor, o funil "
            f"precisa respeitar a variável PORT do .env em vez de fixar a porta no código."
        )

    deployment.app_port = port
    db.session.commit()
