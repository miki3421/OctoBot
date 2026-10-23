"""Create a private approval verifier from an operator-owned local file.

Never accepts a password argument or prints the password/verifier. Does not
deploy, activate accounts or change the dashboard's existing authentication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--credential-file',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('operator_root_required')
    path=Path(args.credential_file);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0:raise ValueError('private_operator_credential_required')
    path.chmod(0o600)
    password=path.read_text().rstrip('\r\n')
    if not 12<=len(password)<=256 or '\n' in password or '\r' in password:
        raise ValueError('one_line_password_12_to_256_characters_required')
    output=Path(args.output)
    if output.exists():raise ValueError('new_verifier_file_required')
    salt=secrets.token_bytes(16)
    value=dict(algorithm='scrypt-v1',salt=salt.hex(),scrypt=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32).hex())
    with output.open('x') as f:json.dump(value,f);f.write('\n')
    os.chown(output,0,30910);output.chmod(0o440)
    print('Verificatore delle approvazioni creato. Nessun servizio attivato.')


if __name__=='__main__':main()
