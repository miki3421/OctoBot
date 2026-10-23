"""Web read model and narrow approval-socket client. No ledger write access."""
import json
import os
from pathlib import Path
import socket
import stat
from . import v13_m1_weekly as weekly

PROJECTION=Path('/v13-paper/m1-paper-ui/management.json')
SOCKET=Path('/v13-paper/m1-management-control/socket/approval.sock')
ACCOUNT='v13-m1-short-paper-v1-5e761f0cedac'


def public_view(path=PROJECTION,control_socket=SOCKET):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=30943 or info.st_mode&0o022 or info.st_size>2000000:raise ValueError('management_projection_custody')
            value=json.loads(os.read(fd,2000001))
        finally:os.close(fd)
        if value['scope']!='M1_WEEKLY_MANAGEMENT_STATUS_V1' or value['account']!=ACCOUNT or value['orders_authorized'] is not False:raise ValueError('management_scope')
        if value.get('proposal'):
            weekly.verify(value['proposal'],'proposal_id')
            if value['proposal']['account']!=ACCOUNT:raise ValueError('proposal_account')
        import datetime as dt
        age=(dt.datetime.now(weekly.UTC)-weekly.when(value['generated_at'])).total_seconds()
        if age<0:raise ValueError('management_future')
        ready=False
        try:
            status=exchange({'operation':'status'},control_socket)
            ready=status.get('scope')=='M1_APPROVAL_WRITER_STATUS_V1' and status.get('account')==ACCOUNT and status.get('authentication_configured') is True
        except (OSError,ValueError,KeyError,TypeError):pass
        value.update(available=True,stale=age>180,approval_ready=ready)
        return value
    except (OSError,ValueError,KeyError,TypeError):
        return dict(available=False,approval_ready=False,message='Selezione settimanale M1 non disponibile o non verificabile.')


def decide(payload,control_socket=SOCKET):
    if not isinstance(payload,dict) or set(payload)!={'proposal_id','action','exclude_short','password','confirmation'}:
        raise ValueError('invalid_approval_request')
    if payload['confirmation']!=payload['proposal_id']:raise ValueError('explicit_confirmation_required')
    if payload['action'] not in ('APPROVE','REJECT') or type(payload['exclude_short']) is not list:
        raise ValueError('invalid_approval_action')
    request={k:v for k,v in payload.items() if k!='confirmation'};request['operation']='decision'
    return exchange(request,control_socket)


def exchange(request,control_socket=SOCKET):
    info=Path(control_socket).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=30945:raise ValueError('approval_socket_custody')
    raw=json.dumps(request).encode()+b'\n'
    if len(raw)>16384:raise ValueError('approval_request_size')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect(str(control_socket))
        import struct
        _,peer_uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if peer_uid!=30945:raise ValueError('approval_peer_identity')
        client.sendall(raw);reply=b''
        while b'\n' not in reply:
            part=client.recv(4096)
            if not part or len(reply)+len(part)>32768:raise ValueError('approval_reply_invalid')
            reply+=part
    value=json.loads(reply)
    if value.get('ok') is not True:raise ValueError('approval_denied')
    return value['decision']
