{{- define "api.check" -}}
{{- if not (regexMatch "^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$" .Values.image) }}{{ fail "image must be <repository>@sha256:<digest>" }}{{ end -}}
{{- if lt (int .Values.replicas) 1 }}{{ fail "replicas must be >= 1" }}{{ end -}}
{{- if and .Values.ingress.enabled (eq (len .Values.ingress.inboundCIDRs) 0) }}{{ fail "ingress.inboundCIDRs is required (VPC CIDR first, ECS SG later)" }}{{ end -}}
{{- range .Values.ingress.inboundCIDRs }}{{ if or (eq . "0.0.0.0/0") (not (regexMatch "^[0-9]{1,3}(\\.[0-9]{1,3}){3}/[0-9]{1,2}$" .)) }}{{ fail "ingress.inboundCIDRs must be private CIDRs, not 0.0.0.0/0" }}{{ end }}{{ end -}}
{{- end -}}

{{- define "api.labels" -}}
app.kubernetes.io/name: {{ .Values.name }}
app.kubernetes.io/part-of: clothes-query
{{- end -}}
