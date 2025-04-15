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
{{- default .Values.rbac.clusterRoleName (printf "%s-cluster-role" .Values.rbac.serviceAccountDriver) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sparkapplication.clusterRoleBindingName" -}}
{{- default .Values.rbac.clusterRoleBindingName (printf "%s-cluster-role-%s" .Values.rbac.serviceAccountDriver .Release.Namespace) | trunc 63 | trimSuffix "-" }}
{{- end }} 