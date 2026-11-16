export type ApiItemKind =
  | 'GET'
  | 'POST'
  | 'PUT'
  | 'DELETE'
  | 'HEAD'
  | 'WSS'
  | 'MCP'
  | 'CLI'
  | 'HOOK'
  | 'SDK'
  | 'CLASS'
  | 'PLUGIN'
  | 'SLOT'
  | 'SCHEMA'
  | 'FRAME'
  | 'CONFIG'

export interface ApiParamField {
  name: string
  location:
    | 'path'
    | 'query'
    | 'header'
    | 'body'
    | 'arg'
    | 'flag'
    | 'slot'
    | 'env'
    | 'stdin'
    | 'field'
    | 'config'
    | 'method'
    | 'event'
    | 'meta'
  type: string
  required?: boolean
  defaultValue?: string
  description: string
}

export interface ApiResponseSpec {
  status: string
  tone: 'ok' | 'warn' | 'err' | 'info'
  summary: string
  example?: string
}

export interface ApiCodeSample {
  label: string
  lang?: string
  code: string
}

export interface ApiItemSpec {
  id: string
  group: string
  kind: ApiItemKind
  title: string
  signature: string
  auth?: string
  stability?: string
  summary: string
  capabilities: string[]
  limitations: string[]
  params?: ApiParamField[]
  responses: ApiResponseSpec[]
  examples: ApiCodeSample[]
  relatedLink?: string
  relatedLabel?: string
}

export interface ApiGroupSpec {
  id: string
  title: string
  description?: string
}

export interface ApiEnvironmentOption {
  label: string
  value: string
}

export interface ApiCatalogLabels {
  allGroups: string
  canDo: string
  cannotDo: string
  params: string
  paramName: string
  paramLocation: string
  paramType: string
  paramRequired: string
  paramDesc: string
  responses: string
  examples: string
  responseSample: string
  copy: string
  copied: string
  noParams: string
  required: string
  optional: string
  deepDocs: string
  totalItems: string
  envLabel: string
  mobilePicker: string
  defaultLabel: string
  plainIndexToggle?: string
}

export interface ApiCatalogSpec {
  project: string
  subtitle: string
  environments?: ApiEnvironmentOption[]
  searchPlaceholder: string
  emptyText: string
  labels: ApiCatalogLabels
  groups: ApiGroupSpec[]
  items: ApiItemSpec[]
}
