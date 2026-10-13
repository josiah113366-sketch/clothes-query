set -euo pipefail
cd /work
mkdir -p authority server connect clients
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=smoke-ca -keyout authority/ca.key -out authority/ca.crt >/dev/null 2>&1
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=rogue-ca -keyout authority/rogue.key -out authority/rogue.crt >/dev/null 2>&1
issue() {
  local identity="$1" destination="$2" issuer="$3" usage="$4"
  openssl req -new -newkey rsa:2048 -nodes -subj "/CN=$identity" -keyout "$destination/key.pem" -out "$destination/request.pem" >/dev/null 2>&1
  printf 'basicConstraints=CA:FALSE\nextendedKeyUsage=%s\n' "$usage" > "$destination/extensions"
  if [ "$identity" = kafka ]; then printf 'subjectAltName=DNS:kafka,DNS:localhost\n' >> "$destination/extensions"; fi
  openssl x509 -req -in "$destination/request.pem" -CA "authority/$issuer.crt" -CAkey "authority/$issuer.key" -CAcreateserial -days 2 -extfile "$destination/extensions" -out "$destination/cert.pem" >/dev/null 2>&1
  cat "$destination/key.pem" "$destination/cert.pem" "authority/$issuer.crt" > "$destination/identity.pem"
  cp authority/ca.crt "$destination/ca.crt"
}
issue kafka server ca serverAuth
issue smoke-connect connect ca clientAuth
mkdir -p clients/reader clients/wrong
issue smoke-reader clients/reader ca clientAuth
issue wrong-client clients/wrong rogue clientAuth
cp authority/ca.crt clients/ca.crt
for identity in reader wrong; do
  cat > "clients/$identity.properties" <<EOF
security.protocol=SSL
ssl.truststore.type=PEM
ssl.truststore.location=/mnt/tls/ca.crt
ssl.keystore.type=PEM
ssl.keystore.location=/mnt/tls/$identity/identity.pem
ssl.endpoint.identification.algorithm=https
request.timeout.ms=2000
default.api.timeout.ms=5000
socket.connection.setup.timeout.ms=2000
socket.connection.setup.timeout.max.ms=2000
EOF
done
cat > clients/no-cert.properties <<EOF
security.protocol=SSL
ssl.truststore.type=PEM
ssl.truststore.location=/mnt/tls/ca.crt
ssl.endpoint.identification.algorithm=https
request.timeout.ms=2000
default.api.timeout.ms=5000
socket.connection.setup.timeout.ms=2000
socket.connection.setup.timeout.max.ms=2000
EOF
