<template>
  <section class="audit-row" :class="{ current, open }">
    <button type="button" class="row-line" :aria-expanded="open" @click="emit('toggle')">
      <span class="row-index">{{ index }}.</span>
      <span class="row-time">{{ time }}</span>
      <span class="row-model">{{ row.model_requested }}</span>
      <span class="row-tags">
        <el-tag :type="row.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ row.status_code }}</el-tag>
        <el-tag v-if="sample" size="small">{{ t('audit.reportSample') }}</el-tag>
        <el-tag v-if="row.keyword_hit" size="small" type="warning">{{ t('audit.reportKeyword') }}</el-tag>
        <el-tag :type="tagType" size="small">{{ tagText }}</el-tag>
      </span>
      <span class="row-preview">{{ preview }}</span>
      <el-icon class="row-chevron" :class="{ flipped: open }"><ArrowDown /></el-icon>
    </button>
    <div v-if="open" class="row-body">
      <p class="verdict-line">{{ line }}</p>
      <pre class="excerpt">{{ text }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'

/** One request in the audit lists: a single line by default, the full excerpt only when opened. */
defineProps<{
  row: { model_requested: string, status_code: number, keyword_hit?: boolean }
  index: number
  time: string
  tagText: string
  tagType: 'success' | 'warning' | 'danger' | 'info' | 'primary'
  line: string
  text: string
  preview: string
  open: boolean
  current?: boolean
  sample?: boolean
}>()
const emit = defineEmits<{ toggle: [] }>()
const { t } = useI18n()
</script>

<style scoped>
.audit-row {
  border-top: 1px solid #ededed;
}

.audit-row.current {
  background: #f4f7ff;
}

.row-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  width: 100%;
  min-height: 36px;
  padding: 6px 4px;
  border: 0;
  background: transparent;
  color: #646a73;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.row-line:hover {
  background: #f7f8fa;
}

.row-line:focus-visible {
  outline: 2px solid #3b5bfd;
  outline-offset: -2px;
}

.row-index {
  min-width: 28px;
  color: #1c1f23;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.row-time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.row-model {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 190px;
}

.row-preview {
  flex: 1 1 160px;
  min-width: 0;
  overflow: hidden;
  color: #86909c;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-chevron {
  flex: none;
  color: #86909c;
  transition: transform 0.15s;
}

.row-chevron.flipped {
  transform: rotate(180deg);
}

.row-body {
  padding: 2px 4px 12px 36px;
}

.verdict-line {
  margin: 0 0 6px;
  color: #1c1f23;
  font-size: 13px;
  line-height: 1.5;
}

.excerpt {
  max-height: 320px;
  margin: 0;
  overflow: auto;
  color: #1d2129;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

@media (max-width: 600px) {
  .row-tags {
    min-width: 0;
  }

  .row-preview {
    flex-basis: 100%;
    order: 9;
  }

  .row-body {
    padding-left: 4px;
  }
}
</style>
