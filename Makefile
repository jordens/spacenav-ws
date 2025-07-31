HOST ?= 127.51.68.120
CERT_DIR := src/spacenav_ws/data/certs
CERT_BASENAME := $(CERT_DIR)/$(HOST)

.PHONY: certs clean-certs

certs:
	mkdir -p "$(CERT_DIR)"
	test ! -e "$(CERT_BASENAME).crt" || { echo "Refusing to overwrite existing $(CERT_BASENAME).crt"; exit 1; }
	test ! -e "$(CERT_BASENAME).key" || { echo "Refusing to overwrite existing $(CERT_BASENAME).key"; exit 1; }
	printf '%s\n' \
		'[ req ]' \
		'default_bits = 2048' \
		'distinguished_name = dn' \
		'req_extensions = req_ext' \
		'x509_extensions = req_ext' \
		'prompt = no' \
		'' \
		'[ dn ]' \
		'CN = $(HOST)' \
		'' \
		'[ req_ext ]' \
		'subjectAltName = @alt_names' \
		'' \
		'[ alt_names ]' \
		'IP.1 = $(HOST)' \
		> "$(CERT_BASENAME).cnf"
	openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
		-keyout "$(CERT_BASENAME).key" \
		-out "$(CERT_BASENAME).crt" \
		-config "$(CERT_BASENAME).cnf" \
		-extensions req_ext

clean-certs:
	rm -f "$(CERT_DIR)"/*.cnf "$(CERT_DIR)"/*.crt "$(CERT_DIR)"/*.key
