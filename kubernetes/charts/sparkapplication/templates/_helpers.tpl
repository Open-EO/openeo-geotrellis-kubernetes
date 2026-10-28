{{/*
Expand the name of the chart.
*/}}
{{- define "sparkapplication.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "sparkapplication.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sparkapplicationlite.fullname" -}}
{{- if .Values.liteFullnameOverride }}
{{- .Values.liteFullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default "lite" .Values.liteNameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "sparkapplication.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "sparkapplication.labels" -}}
helm.sh/chart: {{ include "sparkapplication.chart" . }}
{{ include "sparkapplication.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "sparkapplication.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sparkapplication.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
labels for lite components
*/}}
{{- define "sparkapplication.liteLabels" -}}
helm.sh/chart: {{ include "sparkapplication.chart" . }}
{{ include "sparkapplication.liteSelectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{- define "sparkapplication.liteSelectorLabels" -}}
app.kubernetes.io/name: {{ include "sparkapplication.name" . }}-lite
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "sparkapplication.serviceAccountDriver" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sparkapplication.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}


{{- define "sparkapplication.clusterRoleName" -}}
{{- .Values.rbac.clusterRoleName | default (printf "%s-cluster-role" .Values.rbac.serviceAccountDriver) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sparkapplication.clusterRoleBindingName" -}}
{{- .Values.rbac.clusterRoleBindingName | default (printf "%s-cluster-role-%s" .Values.rbac.serviceAccountDriver .Release.Namespace) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Validate that layerCatalog.viaInitContainer.targetDir is a subdirectory of initdata.targetDir.
Call this template at the top of any template that uses these values.
*/}}
{{- define "sparkapplication.validateInitdata" -}}
  {{- if .Values.layerCatalog.viaInitContainer.enabled }}
    {{- $initdataDir := .Values.initdata.targetDir }}
    {{- $layerCatalogDir := .Values.layerCatalog.viaInitContainer.targetDir }}
    {{- if not (hasPrefix $initdataDir $layerCatalogDir) }}
      {{- fail (printf "layerCatalog.viaInitContainer.targetDir (%q) must start with initdata.targetDir (%q)" $layerCatalogDir $initdataDir) }}
    {{- end }}
  {{- end }}
{{- end }}

{{/*
Whether the shared initdata emptyDir volume is used.
*/}}
{{- define "sparkapplication.initdataEnabled" -}}
{{- if or .Values.initdata.enabled .Values.layerCatalog.viaInitContainer.enabled }}true{{ end }}
{{- end }}

{{/*
All volumes that can be used by the driver and executor pods (YAML list).
*/}}
{{- define "sparkapplication.volumes" -}}
{{- $fullName := include "sparkapplication.fullname" . }}
{{- if include "sparkapplication.initdataEnabled" . }}
- name: initdata
  emptyDir: {}
{{- end }}
{{- with .Values.volumes }}
{{ toYaml . }}
{{- end }}
{{- range $key, $suffix := dict "backendConfig" "backend-config" "batchJobLog4j2" "batch-job-log4j2" "customBatchConfig" "custom-batch-config" "httpCredentials" "http-credentials" "layerCatalog" "layercatalog" "log4j2" "log4j2" "prometheusConfig" "prometheus-config" }}
{{- if index $.Values.configMaps $key }}
- configMap:
    name: {{ $fullName }}-{{ $suffix }}
  name: {{ $fullName }}-{{ $suffix }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Volume mount of the shared initdata volume (YAML list).
*/}}
{{- define "sparkapplication.initdataVolumeMount" -}}
{{- if include "sparkapplication.initdataEnabled" . }}
- mountPath: {{ .Values.initdata.targetDir }}
  name: initdata
{{- end }}
{{- end }}

{{/*
Volume mounts of the driver container (YAML list).
*/}}
{{- define "sparkapplication.driverVolumeMounts" -}}
{{- $fullName := include "sparkapplication.fullname" . }}
{{- with .Values.volumeMounts }}
{{ toYaml . }}
{{- end }}
{{- with .Values.driver.volumeMounts }}
{{ toYaml . }}
{{- end }}
{{- include "sparkapplication.initdataVolumeMount" . }}
{{- if not .Values.existingConfigMaps }}
{{- if .Values.configMaps.backendConfig }}
- mountPath: /opt/backend_config/backendconfig.py
  name: {{ $fullName }}-backend-config
  subPath: backendconfig.py
{{- end }}
{{- if .Values.configMaps.batchJobLog4j2 }}
- mountPath: /opt/batch_job_log4j2.xml
  name: {{ $fullName }}-batch-job-log4j2
  subPath: batch_job_log4j2.xml
{{- end }}
{{- if .Values.configMaps.httpCredentials }}
- mountPath: /opt/http_credentials/http_credentials.json
  name: {{ $fullName }}-http-credentials
  subPath: http_credentials.json
{{- end }}
{{- if .Values.configMaps.customBatchConfig }}
- mountPath: /opt/venv/lib64/python{{ .Values.pythonVersion }}.{{ .Values.pythonMinorVersion }}/site-packages/openeogeotrellis/deploy/sparkapplication.yaml.j2
  name: {{ $fullName }}-custom-batch-config
  subPath: sparkapplication.yaml.j2
{{- end }}
{{- if .Values.configMaps.layerCatalog }}
- mountPath: /opt/layercatalog.json
  name: {{ $fullName }}-layercatalog
  subPath: layercatalog.json
{{- end }}
{{- if .Values.configMaps.log4j2 }}
- mountPath: /opt/log4j2.xml
  name: {{ $fullName }}-log4j2
  subPath: log4j2.xml
{{- end }}
{{- if .Values.configMaps.prometheusConfig }}
- mountPath: /opt/prometheus_config.yaml
  name: {{ $fullName }}-prometheus-config
  subPath: prometheus_config.yaml
{{- end }}
{{- end }}
{{- end }}

{{/*
Volume mounts of the executor container (YAML list).
*/}}
{{- define "sparkapplication.executorVolumeMounts" -}}
{{- $fullName := include "sparkapplication.fullname" . }}
{{- with .Values.volumeMounts }}
{{ toYaml . }}
{{- end }}
{{- with .Values.executor.volumeMounts }}
{{ toYaml . }}
{{- end }}
{{- include "sparkapplication.initdataVolumeMount" . }}
{{- if not .Values.existingConfigMaps }}
{{- if .Values.configMaps.backendConfig }}
- mountPath: /opt/backend_config/backendconfig.py
  name: {{ $fullName }}-backend-config
  subPath: backendconfig.py
{{- end }}
{{- if .Values.configMaps.batchJobLog4j2 }}
- mountPath: /opt/batch_job_log4j2.xml
  name: {{ $fullName }}-batch-job-log4j2
  subPath: batch_job_log4j2.xml
{{- end }}
{{- if .Values.configMaps.httpCredentials }}
- mountPath: /opt/http_credentials/http_credentials.json
  name: {{ $fullName }}-http-credentials
  subPath: http_credentials.json
{{- end }}
{{- if .Values.configMaps.prometheusConfig }}
- mountPath: /opt/prometheus_config.yaml
  name: {{ $fullName }}-prometheus-config
  subPath: prometheus_config.yaml
{{- end }}
{{- if .Values.configMaps.log4j2 }}
- mountPath: /opt/log4j2.xml
  name: {{ $fullName }}-log4j2
  subPath: log4j2.xml
{{- end }}
{{- end }}
{{- end }}

{{/*
Environment variables of the driver container (YAML list).
*/}}
{{- define "sparkapplication.driverEnv" -}}
- name: IMAGE_NAME
  value: {{ .Values.image }}:{{ .Values.imageVersion }}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
{{- if include "sparkapplication.initdataEnabled" . }}
- name: INITDATA_DIR
  value: {{ .Values.initdata.targetDir }}
{{- end }}
{{- with .Values.layerCatalog.viaInitContainer }}
{{- if .enabled }}
- name: LAYER_CATALOG_INIT_DIR
  value: {{ .targetDir }}
- name: LAYER_CATALOG_INIT_IMAGE
  value: {{ .image.repository }}:{{ .image.tag }}
- name: LAYER_CATALOG_INIT_IMAGE_PULL_POLICY
  value: {{ .pullPolicy }}
- name: OPENEO_LAYER_CATALOG_VERSION
  value: {{ .image.tag }}
{{- end }}
{{- end }}
{{- range $key, $value := .Values.driver.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- with .Values.driver.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- with .Values.global.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- if .Values.configMaps.backendConfig }}
- name: OPENEO_BACKEND_CONFIG
  value: "/opt/backend_config/backendconfig.py"
{{- end }}
{{- end }}

{{/*
Environment variables of the executor container (YAML list).
*/}}
{{- define "sparkapplication.executorEnv" -}}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
{{- range $key, $value := .Values.executor.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- with .Values.executor.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- with .Values.global.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Init container that stages the layercatalog files (YAML list).
*/}}
{{- define "sparkapplication.layerCatalogInitContainer" -}}
{{- with .Values.layerCatalog.viaInitContainer }}
{{- if .enabled }}
- name: init-layercatalog
  image: "{{ .image.repository }}:{{ .image.tag }}"
  imagePullPolicy: {{ .pullPolicy }}
  env:
  - name: TARGET_DIR
    value: {{ .targetDir }}
  volumeMounts:
  - name: initdata
    mountPath: {{ $.Values.initdata.targetDir }}
  resources:
    {{- toYaml .resources | nindent 4 }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Init containers of the driver pod (YAML list).
*/}}
{{- define "sparkapplication.driverInitContainers" -}}
{{- with .Values.initContainers }}
{{ toYaml . }}
{{- end }}
{{- with .Values.driver.initContainers }}
{{ toYaml . }}
{{- end }}
{{- include "sparkapplication.layerCatalogInitContainer" . }}
{{- end }}

{{/*
Init containers of the executor pods (YAML list).
*/}}
{{- define "sparkapplication.executorInitContainers" -}}
{{- with .Values.initContainers }}
{{ toYaml . }}
{{- end }}
{{- include "sparkapplication.layerCatalogInitContainer" . }}
{{- end }}

{{/*
Pod templates (podTemplates.enabled)

With pod templates the operator no longer needs its mutating webhook to configure the pods.
Everything the webhook would add (env, volumes, init containers, affinity, ...) is rendered in
spec.{driver,executor}.template instead and left out of spec.{driver,executor}.
*/}}
{{- define "sparkapplication.validatePodTemplates" -}}
  {{- if .Values.podTemplates.enabled }}
    {{- if semverCompare "<3.0.0" (toString .Values.sparkVersion) }}
      {{- fail (printf "podTemplates.enabled requires sparkVersion >= 3.0.0 (got %q)" (toString .Values.sparkVersion)) }}
    {{- end }}
    {{- if .Values.jmxExporterJar }}
      {{- if not (dig "prometheus" "configFile" "" .Values.monitoring) }}
        {{- fail "podTemplates.enabled with jmxExporterJar requires monitoring.prometheus.configFile, otherwise the webhook still adds the prometheus config mount and jmx-exporter port" }}
      {{- end }}
      {{- if or .Values.existingConfigMaps (not .Values.configMaps.prometheusConfig) }}
        {{- fail "podTemplates.enabled with jmxExporterJar requires existingConfigMaps=false and configMaps.prometheusConfig, the chart's prometheus configmap provides metrics.properties" }}
      {{- end }}
    {{- end }}
  {{- end }}
{{- end }}

{{/*
Path of the Spark metrics.properties file, taken from the chart's prometheus configmap.
*/}}
{{- define "sparkapplication.metricsPropertiesFile" -}}
/etc/metrics/conf/metrics.properties
{{- end }}

{{/*
Mount of metrics.properties, only needed with pod templates (YAML list).
*/}}
{{- define "sparkapplication.metricsPropertiesVolumeMount" -}}
{{- if .Values.jmxExporterJar }}
- mountPath: {{ include "sparkapplication.metricsPropertiesFile" . }}
  name: {{ include "sparkapplication.fullname" . }}-prometheus-config
  subPath: metrics.properties
{{- end }}
{{- end }}

{{/*
Container port scraped by the PodMonitor, only needed with pod templates (YAML list).
*/}}
{{- define "sparkapplication.jmxExporterPort" -}}
{{- if .Values.jmxExporterJar }}
- name: jmx-exporter
  containerPort: {{ .Values.jmxPort | default 8090 }}
  protocol: TCP
{{- end }}
{{- end }}

{{/*
Volumes referenced by the given volume mounts and init containers, first occurrence wins.
Mirrors the webhook, which only adds the volumes that a pod mounts.
Arguments: (list $root $volumeMounts $initContainers)
*/}}
{{- define "sparkapplication.usedVolumes" -}}
{{- $root := index . 0 }}
{{- $names := dict }}
{{- range (index . 1) }}{{ $_ := set $names .name true }}{{ end }}
{{- range (index . 2) }}{{ range .volumeMounts }}{{ $_ := set $names .name true }}{{ end }}{{ end }}
{{- $volumes := list }}
{{- range (include "sparkapplication.volumes" $root | fromYamlArray) }}
  {{- if hasKey $names .name }}
    {{- $volumes = append $volumes . }}
    {{- $_ := unset $names .name }}
  {{- end }}
{{- end }}
{{- with $volumes }}{{ toYaml . }}{{ end }}
{{- end }}

{{/*
Pod-level fields shared by the driver and executor templates.
Arguments: (list $root $role) where $role is .Values.driver or .Values.executor
*/}}
{{- define "sparkapplication.podTemplateCommonSpec" -}}
{{- $root := index . 0 }}
{{- $role := index . 1 }}
{{- with $role.podSecurityContext }}
securityContext:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $role.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- if $root.Values.hostNetwork }}
hostNetwork: true
dnsPolicy: ClusterFirstWithHostNet
{{- end }}
{{- with $root.Values.batchScheduler.name }}
{{- if ne . "default-scheduler" }}
schedulerName: {{ . }}
{{- end }}
{{- end }}
{{- if not (kindIs "invalid" $role.terminationGracePeriodSeconds) }}
terminationGracePeriodSeconds: {{ $role.terminationGracePeriodSeconds }}
{{- end }}
{{- end }}

{{/*
spec.driver.template
*/}}
{{- define "sparkapplication.driverPodTemplate" -}}
{{- $mounts := concat (include "sparkapplication.driverVolumeMounts" . | fromYamlArray) (include "sparkapplication.metricsPropertiesVolumeMount" . | fromYamlArray) }}
{{- $initContainers := include "sparkapplication.driverInitContainers" . | fromYamlArray }}
{{- $ports := concat (.Values.driver.ports | default list) (include "sparkapplication.jmxExporterPort" . | fromYamlArray) }}
spec:
  {{- include "sparkapplication.podTemplateCommonSpec" (list . .Values.driver) | nindent 2 }}
  {{- with .Values.driver.priorityClassName | default .Values.priorityClassName }}
  priorityClassName: {{ . }}
  {{- end }}
  {{- with (include "sparkapplication.usedVolumes" (list . $mounts $initContainers)) }}
  volumes:
    {{- . | nindent 4 }}
  {{- end }}
  {{- with $initContainers }}
  initContainers:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  containers:
    - name: spark-kubernetes-driver
      env:
        {{- include "sparkapplication.driverEnv" . | nindent 8 }}
      {{- with $mounts }}
      volumeMounts:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $ports }}
      ports:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      securityContext:
        privileged: {{ .Values.privileged }}
      {{- with .Values.driver.lifecycle }}
      lifecycle:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.driver.startupProbe }}
      startupProbe:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.driver.livenessProbe }}
      livenessProbe:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.driver.readinessProbe }}
      readinessProbe:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}

{{/*
spec.executor.template
*/}}
{{- define "sparkapplication.executorPodTemplate" -}}
{{- $mounts := concat (include "sparkapplication.executorVolumeMounts" . | fromYamlArray) (include "sparkapplication.metricsPropertiesVolumeMount" . | fromYamlArray) }}
{{- $initContainers := include "sparkapplication.executorInitContainers" . | fromYamlArray }}
{{- $ports := include "sparkapplication.jmxExporterPort" . | fromYamlArray }}
spec:
  {{- include "sparkapplication.podTemplateCommonSpec" (list . .Values.executor) | nindent 2 }}
  {{- with (include "sparkapplication.usedVolumes" (list . $mounts $initContainers)) }}
  volumes:
    {{- . | nindent 4 }}
  {{- end }}
  {{- with $initContainers }}
  initContainers:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  containers:
    - name: spark-kubernetes-executor
      env:
        {{- include "sparkapplication.executorEnv" . | nindent 8 }}
      {{- with $mounts }}
      volumeMounts:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $ports }}
      ports:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      securityContext:
        privileged: {{ .Values.privileged }}
      {{- with .Values.executor.lifecycle }}
      lifecycle:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
