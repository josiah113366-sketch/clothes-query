{{- define "cq.check" -}}
{{- if ne .Release.Namespace "kafka" }}{{ fail "Install in namespace kafka; operator is scoped to this namespace" }}{{ end -}}
{{- if and .Values.connect.enabled (not .Values.kafka.enabled) }}{{ fail "connect requires kafka.enabled" }}{{ end -}}
{{- if .Values.kafka.enabled -}}
{{- if not .Values.kafka.storageGi }}{{ fail "kafka.storageGi is required when enabled" }}{{ end -}}
{{- if not .Values.kafka.retentionHours }}{{ fail "kafka.retentionHours is required when enabled" }}{{ end -}}
{{- $names := dict -}}
{{- $reserved := list (printf "%s-configs" .Values.connect.name) (printf "%s-offsets" .Values.connect.name) (printf "%s-status" .Values.connect.name) -}}
{{- range .Values.topics -}}
{{- if or (hasKey $names .name) (has .name $reserved) }}{{ fail "Duplicate or reserved topic name" }}{{ end -}}
{{- $_ := set $names .name true -}}
{{- end -}}
{{- $users := dict -}}
{{- range .Values.clients -}}
{{- if or (hasKey $users .name) (eq .name $.Values.connect.name) }}{{ fail "Duplicate or reserved client name" }}{{ end -}}
{{- $_ := set $users .name true -}}
{{- if eq (len (concat .produceTopics .consumeTopics)) 0 }}{{ fail "Client requires at least one business topic" }}{{ end -}}
{{- range concat .produceTopics .consumeTopics -}}
{{- if not (hasKey $names .) }}{{ fail "Client ACL references an undefined business topic" }}{{ end -}}
{{- end -}}
{{- if and (gt (len .consumeTopics) 0) (eq (len .consumerGroups) 0) }}{{ fail "Consumers require explicit consumerGroups" }}{{ end -}}
{{- end -}}
{{- if .Values.connect.enabled -}}
{{- if not .Values.connect.image }}{{ fail "connect.image digest is required" }}{{ end -}}
{{- if eq (len .Values.connect.produceTopics) 0 }}{{ fail "connect.produceTopics requires explicit business topics" }}{{ end -}}
{{- range .Values.connect.produceTopics -}}
{{- if not (hasKey $names .) }}{{ fail "Connect ACL references an undefined business topic" }}{{ end -}}
{{- end -}}
{{- end -}}
{{- else -}}
{{- if or (gt (len .Values.topics) 0) (gt (len .Values.clients) 0) }}{{ fail "topics/clients require kafka.enabled" }}{{ end -}}
{{- end -}}
{{- end -}}
