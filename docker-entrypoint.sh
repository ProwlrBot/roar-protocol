#!/bin/sh
set -e

case "${ROAR_MODE}" in
  hub)
    echo "Starting ROAR Hub on ${ROAR_HOST}:${ROAR_PORT}"
    exec python -c "
from roar_sdk.hub import ROARHub
import os
hub = ROARHub(host=os.environ.get('ROAR_HOST', '0.0.0.0'), port=int(os.environ.get('ROAR_PORT', '8090')))
hub.serve()
"
    ;;
  agent)
    echo "Starting ROAR Agent Server on ${ROAR_HOST}:${ROAR_PORT}"
    exec python -c "
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage, ROARServer
import os

identity = AgentIdentity(
    display_name=os.environ.get('ROAR_AGENT_NAME', 'roar-agent'),
    capabilities=os.environ.get('ROAR_AGENT_CAPS', 'general').split(','),
)
server = ROARServer(
    identity=identity,
    host=os.environ.get('ROAR_HOST', '0.0.0.0'),
    port=int(os.environ.get('ROAR_PORT', '8089')),
    signing_secret=os.environ.get('ROAR_SECRET', ''),
)

@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    return ROARMessage(
        **{'from': identity, 'to': msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={'echo': msg.payload, 'agent': identity.display_name},
        context={'in_reply_to': msg.id},
    )

server.serve()
"
    ;;
  cli)
    exec roar "$@"
    ;;
  *)
    echo "Unknown ROAR_MODE: ${ROAR_MODE}"
    echo "Use: hub, agent, or cli"
    exit 1
    ;;
esac
