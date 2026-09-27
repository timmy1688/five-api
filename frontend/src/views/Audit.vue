<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.audit') }}</h3>
        <p>{{ t('audit.subtitle') }}</p>
      </div>
    </div>

    <div class="audit-layout">
      <el-card shadow="never" class="people-card" v-loading="loadingPeople">
        <div class="card-title">{{ t('audit.people') }}</div>
        <el-input v-model="keyQuery" :placeholder="t('audit.search')" clearable class="key-search" />
        <el-empty v-if="!filteredPeople.length" :description="t('audit.emptyPeople')" />
        <button
          v-for="person in filteredPeople"
          :key="person.api_key_id"
          type="button"
          class="person"
          :class="{ active: person.api_key_id === selectedId }"
          :disabled="reviewing"
          @click="selectPerson(person.api_key_id)"
        >
          <span class="person-name">{{ person.api_key_name }}</span>
          <span class="person-count">{{ person.request_count }}</span>
        </button>
      </el-card>

      <el-card shadow="never" class="request-card" v-loading="loadingRequests">
        <el-empty v-if="!selectedPerson" :description="t('audit.pick')" />
        <template v-else>
          <div class="case-head">
            <div>
              <div class="card-title">{{ selectedPerson.api_key_name }}</div>
              <p v-if="!loadingRequests" class="case-count">{{ t('audit.saved', { count: requests.length }) }}</p>
              <p v-if="!loadingRequests && requests.length" class="case-count">{{ reportRange }}</p>
              <p v-if="!aiEnabled" class="case-count">{{ t('audit.needSwitch') }}</p>
            </div>
            <div class="case-actions">
              <el-button v-if="requests.length" :disabled="reviewing" @click="showReport">
                {{ reportVisible ? t('audit.viewReport') : t('audit.generate') }}
              </el-button>
              <el-button
                v-if="auth.hasPermission('security:write') && requests.length"
                type="primary"
                :disabled="!aiEnabled"
                :loading="reviewing"
                @click="reviewKey"
              >
                {{ t('audit.review') }}
              </el-button>
            </div>
          </div>
          <ol v-if="requests.length" class="steps">
            <li :class="stepClass(1)"><span>1</span>{{ t('audit.stepRequests') }}</li>
            <li :class="stepClass(2)"><span>2</span>{{ t('audit.stepReview') }}</li>
            <li :class="stepClass(3)"><span>3</span>{{ t('audit.stepReport') }}</li>
          </ol>
          <div v-if="reviewing || reviewFinished" class="review-progress" :class="{ active: reviewing, done: reviewFinished && !reviewing }">
            <div class="progress-label">
              <i v-if="reviewing" class="pulse" />
              <template v-if="reviewing">{{ t('audit.progress', { index: reviewIndex, total: reviewTotal }) }}</template>
              <template v-else>{{ t('audit.progressDone', { time: elapsedText }) }}</template>
            </div>
            <el-progress
              :percentage="reviewPercent"
              :stroke-width="10"
              :striped="reviewing"
              striped-flow
              :status="reviewFinished && !reviewing ? 'success' : undefined"
            />
            <div class="count-row">
              <span>{{ t('audit.progressElapsed', { time: elapsedText }) }}</span>
              <span v-if="reviewing">{{ t('audit.progressLeft', { count: waitingCount }) }}</span>
              <span>{{ t('logs.aiClear') }} {{ runCounts.clear }}</span>
              <span>{{ t('logs.aiFlagged') }} {{ runCounts.flagged }}</span>
              <span>{{ t('logs.aiUnavailable') }} {{ runCounts.unavailable }}</span>
              <span>{{ t('logs.aiSkipped') }} {{ runCounts.skipped }}</span>
            </div>
            <p v-if="reviewing" class="progress-current">{{ t('audit.progressCalling') }}</p>
            <p v-if="reviewing" class="progress-current">{{ t('audit.progressItemWait', { time: itemWaitText }) }}</p>
            <p v-if="reviewing && reviewCurrent" class="progress-current">{{ reviewCurrent }}</p>
            <p v-if="reviewFinished && !reviewing" class="progress-current">{{ t('audit.progressReportReady') }}</p>
          </div>
          <el-empty v-if="!loadingRequests && !requests.length" :description="t('audit.emptyRequests')" />
          <article v-if="requests.length" ref="reportPaper" class="report report-paper" :class="reportVisible ? 'ready' : 'preview'">
            <div class="paper-head">
              <div>
                <h4>{{ t('audit.reportTitle') }}</h4>
                <p class="case-count">{{ reportVisible ? t('audit.reportFilled', { time: reportGeneratedAt }) : t('audit.reportPreview') }}</p>
              </div>
              <el-button v-if="reportVisible" type="primary" @click="downloadReport">{{ t('audit.download') }}</el-button>
              <el-button v-else type="primary" :disabled="reviewing" @click="showReport">{{ t('audit.generate') }}</el-button>
            </div>
            <div class="stat-row">
              <div><strong>{{ reportCounts.clear }}</strong><span>{{ t('logs.aiClear') }}</span></div>
              <div><strong>{{ reportCounts.flagged }}</strong><span>{{ t('logs.aiFlagged') }}</span></div>
              <div><strong>{{ reportCounts.unavailable }}</strong><span>{{ t('logs.aiUnavailable') }}</span></div>
              <div><strong>{{ reportCounts.skipped }}</strong><span>{{ t('logs.aiSkipped') }}</span></div>
              <div><strong>{{ reportCounts.unreviewed }}</strong><span>{{ t('audit.reportUnreviewed') }}</span></div>
            </div>
            <p><span>{{ t('audit.reportSubject') }}</span>{{ selectedPerson.api_key_name }}</p>
            <p><span>{{ t('audit.reportGenerated') }}</span>{{ reportVisible ? reportGeneratedAt : t('audit.reportPreviewTime') }}</p>
            <p><span>{{ t('audit.reportRange') }}</span>{{ reportRange }}</p>
            <h4>{{ t('audit.reportConclusion') }}</h4>
            <p v-for="(line, index) in reportConclusions" :key="index" class="report-line">{{ line }}</p>
            <h4>{{ t('audit.reportDetails') }}</h4>
            <div class="report-details">
              <section v-for="(row, index) in reportRows" :key="row.request_id" class="report-item">
                <div class="request-meta">
                  <strong>{{ index + 1 }}.</strong>
                  <span>{{ formatTime(row.created_at) }}</span>
                  <span>{{ row.model_requested }}</span>
                  <el-tag :type="row.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ row.status_code }}</el-tag>
                  <el-tag v-if="!reportVisible" size="small">{{ t('audit.reportSample') }}</el-tag>
                  <el-tag v-if="row.keyword_hit" size="small" type="warning">{{ t('audit.reportKeyword') }}</el-tag>
                  <el-tag :type="verdictTag(row.ai_review)" size="small">{{ verdictLabel(row.ai_review) || t('audit.reportUnreviewed') }}</el-tag>
                </div>
                <p class="verdict-line">{{ verdictDetail(row.ai_review) || t('audit.reportUnreviewed') }}</p>
                <pre class="excerpt" :class="{ open: isOpen(row.request_id) }">{{ rowText(row) }}</pre>
                <button v-if="canExpand(row)" type="button" class="expand" @click="toggleOpen(row.request_id)">
                  {{ isOpen(row.request_id) ? t('audit.collapse') : t('audit.expand') }}
                </button>
              </section>
            </div>
            <p v-if="!reportVisible && requests.length > 1" class="case-count sample-note">
              {{ t('audit.reportSampleNote', { count: requests.length - 1 }) }}
            </p>
          </article>
          <section v-if="requests.length" ref="listBox" class="request-list">
            <h4>{{ t('audit.requestsHeading') }}</h4>
            <p class="case-count">{{ t('audit.savedHint') }}</p>
            <section
              v-for="(row, index) in requests"
              :key="row.request_id"
              :ref="(el) => setRowRef(row.request_id, el)"
              class="report-item"
              :class="{ current: row.request_id === reviewingId }"
            >
              <div class="request-meta">
                <strong>{{ index + 1 }}.</strong>
                <span>{{ formatTime(row.created_at) }}</span>
                <span>{{ row.model_requested }}</span>
                <el-tag :type="row.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ row.status_code }}</el-tag>
                <el-tag v-if="row.keyword_hit" size="small" type="warning">{{ t('audit.reportKeyword') }}</el-tag>
                <el-tag v-if="row.request_id === reviewingId" type="primary" size="small">{{ t('audit.reviewingRow') }}</el-tag>
                <el-tag v-else-if="reviewing && !isRunDone(row.request_id)" type="info" size="small">{{ t('audit.rowWaiting') }}</el-tag>
                <el-tag v-else :type="verdictTag(row.ai_review)" size="small">{{ verdictLabel(row.ai_review) || t('audit.reportUnreviewed') }}</el-tag>
              </div>
              <p class="verdict-line">{{ rowVerdictLine(row) }}</p>
              <pre class="excerpt" :class="{ open: isOpen(row.request_id) }">{{ rowText(row) }}</pre>
              <button v-if="canExpand(row)" type="button" class="expand" @click="toggleOpen(row.request_id)">
                {{ isOpen(row.request_id) ? t('audit.collapse') : t('audit.expand') }}
              </button>
            </section>
          </section>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import { auditApi } from '@/api/audit'
import { securityApi } from '@/api/security'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const loadingPeople = ref(false)
const loadingRequests = ref(false)
const reviewing = ref(false)
const reviewFinished = ref(false)
const reviewTotal = ref(0)
const reviewDone = ref(0)
const reviewingId = ref('')
const reviewCurrent = ref('')
const reviewStartedAt = ref(0)
const itemStartedAt = ref(0)
const reviewElapsedMs = ref(0)
const nowTick = ref(Date.now())
const runVerdicts = ref<Record<string, string>>({})
const reportVisible = ref(false)
const reportGeneratedAt = ref('')
const reportPaper = ref<HTMLElement | null>(null)
const listBox = ref<HTMLElement | null>(null)
const rowEls = new Map<string, HTMLElement>()
let clock = 0
const aiEnabled = ref(false)
const people = ref<any[]>([])
const keyQuery = ref('')
const requests = ref<any[]>([])
const selectedId = ref<number | null>(null)
const openRows = ref<Record<string, boolean>>({})

const selectedPerson = computed(() => people.value.find(person => person.api_key_id === selectedId.value) || null)
const shownRequests = computed(() => [...requests.value].sort((a, b) => concernRank(a.ai_review) - concernRank(b.ai_review)))
const reportRows = computed(() => reportVisible.value ? shownRequests.value : shownRequests.value.slice(0, 1))
const reportCounts = computed(() => {
  const counts = countsOf(requests.value)
  return {
    ...counts,
    unreviewed: requests.value.filter(row => !verdictLabel(row.ai_review)).length,
  }
})
const runCounts = computed(() => countsOf(Object.values(runVerdicts.value).map(ai_review => ({ ai_review }))))
const waitingCount = computed(() => {
  const finished = Object.keys(runVerdicts.value).length
  const current = reviewing.value && reviewDone.value < reviewTotal.value ? 1 : 0
  return Math.max(0, reviewTotal.value - finished - current)
})
const elapsedText = computed(() => formatDuration(reviewing.value ? nowTick.value - reviewStartedAt.value : reviewElapsedMs.value))
const itemWaitText = computed(() => formatDuration(nowTick.value - itemStartedAt.value))
const reviewIndex = computed(() => {
  if (!reviewTotal.value) return 0
  const current = reviewDone.value + (reviewing.value && reviewDone.value < reviewTotal.value ? 1 : 0)
  return Math.min(current, reviewTotal.value)
})
const reviewPercent = computed(() => {
  if (!reviewTotal.value) return 0
  return Math.round(reviewDone.value / reviewTotal.value * 100)
})
const reportRange = computed(() => {
  if (!requests.value.length) return ''
  const times = requests.value.map(row => dayjs(row.created_at))
  const start = times.reduce((earliest, time) => time.isBefore(earliest) ? time : earliest)
  const end = times.reduce((latest, time) => time.isAfter(latest) ? time : latest)
  return t('audit.reportRangeValue', {
    start: start.format('YYYY-MM-DD HH:mm:ss'),
    end: end.format('YYYY-MM-DD HH:mm:ss'),
  })
})
const reportConclusions = computed(() => {
  const counts = countsOf(requests.value)
  const unreviewed = requests.value.filter(row => !verdictLabel(row.ai_review)).length
  const lines: string[] = []
  if (counts.flagged) lines.push(t('audit.reportFlagged', { count: counts.flagged }))
  if (counts.clear) lines.push(t('audit.reportClearCount', { count: counts.clear }))
  if (counts.unavailable) lines.push(t('audit.reportIncomplete', { count: counts.unavailable }))
  if (counts.skipped) lines.push(t('audit.reportSkipped', { count: counts.skipped }))
  if (unreviewed) lines.push(t('audit.reportUnreviewedCount', { count: unreviewed }))
  if (!lines.length) lines.push(t('audit.reportClear'))
  return lines
})
const reportText = computed(() => {
  if (!selectedPerson.value || !requests.value.length) return ''
  const lines = [
    t('audit.reportTitle'),
    `${t('audit.reportSubject')}：${selectedPerson.value.api_key_name}`,
    `${t('audit.reportGenerated')}：${reportGeneratedAt.value}`,
    `${t('audit.reportRange')}：${reportRange.value}`,
    '',
    t('audit.reportConclusion'),
    ...reportConclusions.value,
    '',
    t('audit.reportDetails'),
  ]
  shownRequests.value.forEach((row, index) => {
    const verdict = verdictLabel(row.ai_review) || t('audit.reportUnreviewed')
    const detail = verdictDetail(row.ai_review) || t('audit.reportUnreviewed')
    const keyword = row.keyword_hit ? `，${t('audit.reportKeyword')}` : ''
    lines.push(
      `${index + 1}. ${formatTime(row.created_at)}  ${row.model_requested}  ${row.status_code}  ${verdict}${keyword}`,
      detail,
      rowText(row),
      '',
    )
  })
  return lines.join('\n')
})
const filteredPeople = computed(() => {
  const query = keyQuery.value.trim().toLowerCase()
  if (!query) return people.value
  return people.value.filter(person => String(person.api_key_name || '').toLowerCase().includes(query))
})

function formatTime(value: string) {
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

function formatDuration(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes <= 0) return t('audit.durationSeconds', { count: seconds })
  return t('audit.durationMinutes', { minutes, seconds })
}

function startClock() {
  stopClock()
  nowTick.value = Date.now()
  clock = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
}

function stopClock() {
  if (!clock) return
  window.clearInterval(clock)
  clock = 0
}

function stepClass(step: number) {
  if (step === 1) return { current: !reviewing.value && !reportVisible.value, done: reviewing.value || reviewFinished.value || reportVisible.value }
  if (step === 2) return { current: reviewing.value, done: reviewFinished.value }
  return { current: reportVisible.value && !reviewing.value, done: false }
}

function isRunDone(id: string) {
  return Object.prototype.hasOwnProperty.call(runVerdicts.value, id)
}

function rowVerdictLine(row: { request_id: string, ai_review: string }) {
  if (row.request_id === reviewingId.value) return t('audit.reviewingRow')
  if (reviewing.value && !isRunDone(row.request_id)) return t('audit.rowWaiting')
  return verdictDetail(row.ai_review) || t('audit.reportUnreviewed')
}

function setRowRef(id: string, el: unknown) {
  if (el instanceof HTMLElement) rowEls.set(id, el)
  else rowEls.delete(id)
}

async function focusRow(id: string) {
  await nextTick()
  const row = rowEls.get(id)
  const box = listBox.value
  if (!row || !box) return
  const rowRect = row.getBoundingClientRect()
  const boxRect = box.getBoundingClientRect()
  const delta = rowRect.top - boxRect.top - box.clientHeight / 2 + rowRect.height / 2
  box.scrollTo({ top: Math.max(0, box.scrollTop + delta), behavior: 'smooth' })
}

function verdictTag(value: string) {
  if (!value) return 'info'
  if (value === 'clear') return 'success'
  if (String(value || '').startsWith('flagged:')) return 'danger'
  if (value === 'unavailable') return 'info'
  return 'warning'
}

function verdictLabel(value: string) {
  if (value === 'clear') return t('logs.aiClear')
  if (String(value || '').startsWith('flagged:')) return t('logs.aiFlagged')
  if (value === 'unavailable') return t('logs.aiUnavailable')
  if (value === 'skipped') return t('logs.aiSkipped')
  return ''
}

const categoryLabels = {
  credential: 'audit.category.credential',
  personal: 'audit.category.personal',
  confidential: 'audit.category.confidential',
  other: 'audit.category.other',
} as const

function verdictDetail(value: string) {
  if (value === 'clear') return t('audit.resultClear')
  if (String(value || '').startsWith('flagged:')) {
    const category = value.slice('flagged:'.length)
    const key = categoryLabels[category as keyof typeof categoryLabels] ?? categoryLabels.other
    return t('audit.resultFlagged', { category: t(key) })
  }
  if (value === 'unavailable') return t('audit.resultUnavailable')
  if (value === 'skipped') return t('audit.resultSkipped')
  return ''
}

function concernRank(value: string) {
  if (String(value || '').startsWith('flagged:')) return 0
  if (value === 'unavailable') return 1
  return 2
}

function countsOf(items: any[]) {
  return {
    clear: items.filter(item => item.ai_review === 'clear').length,
    flagged: items.filter(item => String(item.ai_review || '').startsWith('flagged:')).length,
    unavailable: items.filter(item => item.ai_review === 'unavailable').length,
    skipped: items.filter(item => item.ai_review === 'skipped').length,
  }
}

async function loadPeople() {
  loadingPeople.value = true
  try {
    const data = await auditApi.keys()
    people.value = data.items || []
  } catch {
    ElMessage.error(t('audit.loadFailed'))
  } finally {
    loadingPeople.value = false
  }
}

function rowText(row: any) {
  return String(row?.saved || row?.excerpt || t('audit.noExcerpt'))
}

function canExpand(row: any) {
  return rowText(row).length > 280
}

function isOpen(id: string) {
  return !!openRows.value[id]
}

function toggleOpen(id: string) {
  openRows.value = { ...openRows.value, [id]: !openRows.value[id] }
}

function excerptPreview(row: any) {
  const text = String(row?.excerpt || row?.saved || '').replace(/\s+/g, ' ').trim()
  if (!text) return t('audit.noExcerpt')
  return text.length > 80 ? `${text.slice(0, 80)}…` : text
}

async function showReport() {
  if (!reportVisible.value) {
    reportGeneratedAt.value = dayjs().format('YYYY-MM-DD HH:mm:ss')
    reportVisible.value = true
  }
  await nextTick()
  reportPaper.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function selectPerson(id: number) {
  if (reviewing.value) return
  reportVisible.value = false
  reportGeneratedAt.value = ''
  reviewFinished.value = false
  reviewElapsedMs.value = 0
  runVerdicts.value = {}
  selectedId.value = id
  requests.value = []
  loadingRequests.value = true
  try {
    const first = await auditApi.requests(id, 1)
    const items = [...(first.items || [])]
    const total = first.total || items.length
    let page = 2
    while (items.length < total) {
      const next = await auditApi.requests(id, page)
      const batch = next.items || []
      if (!batch.length) break
      items.push(...batch)
      page += 1
    }
    requests.value = items
  } catch {
    ElMessage.error(t('audit.loadFailed'))
  } finally {
    loadingRequests.value = false
  }
}

function downloadReport() {
  const name = String(selectedPerson.value?.api_key_name || 'key').replace(/[^\w\u4e00-\u9fff-]+/g, '-')
  const blob = new Blob([reportText.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `audit-${name}-${dayjs().format('YYYYMMDD-HHmm')}.txt`
  link.click()
  URL.revokeObjectURL(url)
}

async function reviewKey() {
  const ids = requests.value.map(row => row.request_id)
  if (!ids.length) return
  const personId = selectedId.value
  reviewing.value = true
  reviewFinished.value = false
  reportVisible.value = false
  reviewTotal.value = ids.length
  reviewDone.value = 0
  runVerdicts.value = {}
  reviewStartedAt.value = Date.now()
  itemStartedAt.value = Date.now()
  startClock()
  const verdicts = new Map<string, string>()
  try {
    for (const id of ids) {
      if (selectedId.value !== personId) return
      const row = requests.value.find(item => item.request_id === id)
      reviewingId.value = id
      reviewCurrent.value = excerptPreview(row)
      itemStartedAt.value = Date.now()
      await focusRow(id)
      const data = await auditApi.review([id])
      const item = (data.items || []).find((entry: { request_id: string }) => entry.request_id === id)
      if (item) {
        verdicts.set(item.request_id, item.ai_review)
        runVerdicts.value = { ...runVerdicts.value, [item.request_id]: item.ai_review }
        requests.value = requests.value.map(entry => (
          entry.request_id === id ? { ...entry, ai_review: item.ai_review } : entry
        ))
      }
      reviewDone.value += 1
    }
    reviewElapsedMs.value = Date.now() - reviewStartedAt.value
    reviewFinished.value = true
    reviewing.value = false
    ElMessage.success(t('audit.reviewed', countsOf(requests.value.filter(row => verdicts.has(row.request_id)))))
    await showReport()
  } catch {
    ElMessage.error(t('audit.reviewFailed'))
    if (reviewDone.value) {
      reviewElapsedMs.value = Date.now() - reviewStartedAt.value
      reviewFinished.value = true
      await showReport()
    }
  } finally {
    reviewing.value = false
    reviewingId.value = ''
    reviewCurrent.value = ''
    stopClock()
  }
}

onUnmounted(stopClock)

onMounted(async () => {
  try {
    const security = await securityApi.get()
    aiEnabled.value = !!security.ai_audit?.enabled && !!security.ai_audit?.model
  } catch {
    aiEnabled.value = false
  }
  await loadPeople()
})
</script>

<style scoped>
.case-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.case-head > div:first-child {
  flex: 1 1 360px;
}

.case-count {
  margin: 0;
  color: #646a73;
  font-size: 13px;
  line-height: 1.6;
}

.case-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

.steps {
  display: flex;
  gap: 8px;
  margin: 0 0 12px;
  padding: 0;
  list-style: none;
}

.steps li {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f5f6f7;
  color: #8a9099;
  font-size: 13px;
  font-weight: 650;
}

.steps li span {
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #e6e8ea;
  font-size: 12px;
}

.steps li.current {
  background: #e8f3ff;
  color: #0958d9;
}

.steps li.current span,
.steps li.done span {
  background: #1677ff;
  color: #fff;
}

.steps li.done {
  color: #1c1f23;
}

.review-progress {
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid #d6e4ff;
  border-radius: 8px;
  background: #f4f7ff;
}

.review-progress.active {
  position: sticky;
  top: 0;
  z-index: 4;
}

.review-progress.done {
  border-color: #b7ebc6;
  background: #f3fbf5;
}

.pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 6px;
  border-radius: 50%;
  background: #1677ff;
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  50% { opacity: 0.3; }
}

.count-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 8px;
  color: #1c1f23;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.progress-label {
  margin-bottom: 8px;
  font-weight: 650;
}

.progress-current {
  margin: 8px 0 0;
  color: #1c1f23;
  font-size: 13px;
  line-height: 1.5;
}

.request-list {
  max-height: 440px;
  margin-top: 16px;
  overflow: auto;
}

.request-list h4,
.report h4 {
  margin: 16px 0 8px;
}

.report-paper {
  margin-top: 4px;
  padding: 20px 22px 8px;
  border: 1px solid #d9dce3;
  border-radius: 10px;
  background: #fff;
}

.report-paper.preview {
  border-style: dashed;
  background: #fafafa;
}

.report-paper.ready {
  border-style: solid;
  background: #fff;
  box-shadow: 0 0 0 3px #e8f3ff;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0;
}

.stat-row div {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #ededed;
}

.stat-row strong {
  display: block;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.stat-row span {
  color: #646a73;
  font-size: 12px;
}

.report-details {
  max-height: 360px;
  overflow: auto;
}

.sample-note {
  margin-top: 8px;
}

.paper-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.paper-head h4 {
  margin-top: 0;
}

.report-item.current {
  margin: 0 -8px;
  padding: 12px 8px;
  border-radius: 8px;
  background: #f4f7ff;
}

.person:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.report h4 {
  margin: 16px 0 8px;
  font-size: 14px;
}

.report p {
  margin: 0 0 6px;
  color: #1c1f23;
  font-size: 13px;
  line-height: 1.6;
}

.report p span {
  display: inline-block;
  min-width: 72px;
  color: #646a73;
}

.report-item {
  padding: 12px 0;
  border-top: 1px solid #ededed;
}

.audit-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.request-card {
  min-width: 0;
}

.select-all {
  margin-bottom: 4px;
}

.request-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 0;
  border-bottom: 1px solid #ededed;
}

.request-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.request-main {
  min-width: 0;
  flex: 1;
}

.request-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
  color: #646a73;
  font-size: 13px;
}

.verdict-line {
  margin-top: 6px;
  color: #1c1f23;
  font-size: 13px;
  line-height: 1.5;
}

.card-title {
  margin-bottom: 8px;
  font-weight: 650;
}

.key-search {
  margin-bottom: 8px;
}

.person {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 0 4px;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.person.active {
  background: #eef2ff;
}

.person-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.person-count {
  color: #646a73;
  font-variant-numeric: tabular-nums;
}

.excerpt {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
  color: #1d2129;
}

.excerpt.open {
  max-height: none;
}

.expand {
  margin-top: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #3b5bfd;
  font-size: 12px;
  cursor: pointer;
}

.review-result {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #ededed;
}

.review-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.review-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
  font-size: 13px;
  line-height: 1.5;
  color: #1c1f23;
}

.review-time {
  color: #646a73;
  font-variant-numeric: tabular-nums;
}

.muted {
  color: #c0c4cc;
}

@media (max-width: 900px) {
  .audit-layout {
    grid-template-columns: 1fr;
  }

  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .steps {
    flex-direction: column;
  }
}
</style>
