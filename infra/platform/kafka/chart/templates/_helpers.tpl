{{- define "cq.check" -}}
{{- if and (eq .Values.profile "single-node") (or (ne (int .Values.kafka.replicas) 1) (ne (int .Values.connect.replicas) 1)) }}{{ fail "single-node profile requires one Kafka and one Connect replica" }}{{ end -}}
{{- if ne .Release.Namespace "kafka" }}{{ fail "Install in namespace kafka; operator is scoped to this namespace" }}{{ end -}}
{{- if and .Values.connect.enabled (not .Values.kafka.enabled) }}{{ fail "connect requires kafka.enabled" }}{{ end -}}
{{- if and .Values.metrics.enabled (not .Values.kafka.enabled) }}{{ fail "metrics requires kafka.enabled" }}{{ end -}}
{{- if .Values.metrics.lagExporter.enabled -}}
{{- if not .Values.metrics.enabled }}{{ fail "lagExporter requires metrics.enabled" }}{{ end -}}
{{- if or (not (trim .Values.metrics.lagExporter.topicRegex)) (not (trim .Values.metrics.lagExporter.groupRegex)) }}{{ fail "lagExporter requires explicit topicRegex and groupRegex" }}{{ end -}}
{{- $_ := mustRegexMatch .Values.metrics.lagExporter.topicRegex "" -}}
{{- $_ := mustRegexMatch .Values.metrics.lagExporter.groupRegex "" -}}
{{- end -}}
{{- if .Values.kafka.enabled -}}
{{- if not .Values.kafka.storageGi }}{{ fail "kafka.storageGi is required when enabled" }}{{ end -}}
{{- if not .Values.kafka.retentionHours }}{{ fail "kafka.retentionHours is required when enabled" }}{{ end -}}
{{- $names := dict -}}
{{- $resourceNames := dict -}}
{{- $reserved := list (printf "%s-configs" .Values.connect.name) (printf "%s-offsets" .Values.connect.name) (printf "%s-status" .Values.connect.name) -}}
{{- range .Values.topics -}}
{{- if or (hasKey $names .name) (has .name $reserved) }}{{ fail "Duplicate or reserved topic name" }}{{ end -}}
{{- $_ := set $names .name true -}}
{{- $resourceName := default .name .resourceName -}}
{{- if or (gt (len $resourceName) 253) (not (regexMatch "^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$" $resourceName)) }}{{ fail "Topic name needs a DNS-compatible resourceName" }}{{ end -}}
{{- if has $resourceName $reserved }}{{ fail "Reserved KafkaTopic resourceName" }}{{ end -}}
{{- if hasKey $resourceNames $resourceName }}{{ fail "Duplicate KafkaTopic resourceName" }}{{ end -}}
{{- $_ := set $resourceNames $resourceName true -}}
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
{{- range concat .Values.connect.produceTopics .Values.connect.consumeTopics -}}
{{- if not (hasKey $names .) }}{{ fail "Connect ACL references an undefined business topic" }}{{ end -}}
{{- end -}}
{{- if and (gt (len .Values.connect.consumeTopics) 0) (eq (len .Values.connect.consumerGroups) 0) }}{{ fail "Connect consumers require explicit consumerGroups" }}{{ end -}}
{{- end -}}
{{- else -}}
{{- if or (gt (len .Values.topics) 0) (gt (len .Values.clients) 0) }}{{ fail "topics/clients require kafka.enabled" }}{{ end -}}
{{- end -}}
{{- end -}}

{{- define "cq.replicationFactor" -}}{{- if eq .Values.profile "single-node" -}}1{{- else -}}3{{- end -}}{{- end -}}
{{- define "cq.minIsr" -}}{{- if eq .Values.profile "single-node" -}}1{{- else -}}2{{- end -}}{{- end -}}
