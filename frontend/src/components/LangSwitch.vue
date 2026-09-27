<template>
  <div class="lang-switch" role="group" :aria-label="t('lang.label')">
    <button type="button" :class="{ active: locale.current === 'zh' }" @click="locale.setLocale('zh')">中文</button>
    <button type="button" :class="{ active: locale.current === 'en' }" @click="locale.setLocale('en')">EN</button>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'

const { t, locale } = useI18n()
</script>

<style scoped>
.lang-switch {
  display: inline-flex;
  border: 1px solid #e6e8ea;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}

.lang-switch button {
  border: 0;
  background: transparent;
  color: #646a73;
  font-size: 12px;
  line-height: 1;
  padding: 6px 8px;
  cursor: pointer;
}

.lang-switch button.active {
  background: #e8f3ff;
  color: #1677ff;
  font-weight: 600;
}
</style>
