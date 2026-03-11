#!/usr/bin/env python3
import os
import datetime
import ipaddress
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def generate_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

def save_key(key, path):
    with open(path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

def save_cert(cert, path):
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def generate_certs(output_dir="certs", hostname="localhost"):
    out_path = Path(output_dir)
    out_path.mkdir(exist_ok=True)
    
    # 1. Generate Root CA
    ca_key = generate_key()
    save_key(ca_key, out_path / "ca.key")
    
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SentinelEdge"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SentinelEdge Root CA"),
    ])
    
    ca_cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        ca_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True,
    ).sign(ca_key, hashes.SHA256())
    
    save_cert(ca_cert, out_path / "ca.crt")
    print(f"✓ Generated Root CA: {out_path / 'ca.crt'}")
    
    # 2. Generate Server Certificate
    server_key = generate_key()
    save_key(server_key, out_path / "server.key")
    
    server_subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SentinelEdge"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    
    server_cert = x509.CertificateBuilder().subject_name(
        server_subject
    ).issuer_name(
        ca_cert.subject
    ).public_key(
        server_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(hostname), x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]),
        critical=False,
    ).sign(ca_key, hashes.SHA256())
    
    save_cert(server_cert, out_path / "server.crt")
    print(f"✓ Generated Server Cert: {out_path / 'server.crt'}")
    
    # 3. Generate Agent Certificate
    agent_key = generate_key()
    save_key(agent_key, out_path / "agent.key")
    
    agent_subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SentinelEdge"),
        x509.NameAttribute(NameOID.COMMON_NAME, "SentinelEdge-Agent"),
    ])
    
    agent_cert = x509.CertificateBuilder().subject_name(
        agent_subject
    ).issuer_name(
        ca_cert.subject
    ).public_key(
        agent_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).sign(ca_key, hashes.SHA256())
    
    save_cert(agent_cert, out_path / "agent.crt")
    print(f"✓ Generated Agent Cert: {out_path / 'agent.crt'}")

if __name__ == "__main__":
    generate_certs()
