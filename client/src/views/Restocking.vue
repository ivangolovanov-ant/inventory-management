<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
          <span class="budget-display">{{ formatCurrency(budget, currentCurrency) }}</span>
        </div>
        <input
          type="range"
          v-model.number="budget"
          min="0"
          :max="maxBudget"
          step="100"
          class="budget-slider"
        />
        <div class="budget-stats">
          <div class="stat-card info">
            <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
            <div class="stat-value">{{ recommendations.length }}</div>
          </div>
          <div class="stat-card success">
            <div class="stat-label">{{ t('restocking.allocated') }}</div>
            <div class="stat-value">{{ formatCurrency(allocatedTotal, currentCurrency) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">{{ t('restocking.remaining') }}</div>
            <div class="stat-value">{{ formatCurrency(remainingBudget, currentCurrency) }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.qty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!recommendations.length">
                <td colspan="7" class="empty-cell">{{ t('restocking.noRecommendations') }}</td>
              </tr>
              <tr v-for="r in recommendations" :key="r.sku">
                <td><strong>{{ r.sku }}</strong></td>
                <td>{{ r.name }}</td>
                <td>
                  <span :class="['badge', getTrendClass(r.trend)]">
                    {{ t(`trends.${r.trend}`) }}
                  </span>
                </td>
                <td>{{ r.quantity }}</td>
                <td>{{ formatCurrency(r.unit_price, currentCurrency) }}</td>
                <td><strong>{{ formatCurrency(r.quantity * r.unit_price, currentCurrency) }}</strong></td>
                <td>{{ r.lead_time_days }} days</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="successMessage" class="success-banner">
        {{ successMessage }}
      </div>

      <button
        class="btn-primary"
        @click="placeOrder"
        :disabled="!recommendations.length || submitting"
      >
        {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
      </button>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const forecasts = ref([])
    const budget = ref(10000)
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)

    const maxBudget = computed(() => {
      if (!forecasts.value.length) return 100
      const total = forecasts.value.reduce((sum, f) => sum + f.forecasted_demand * f.unit_cost, 0)
      return Math.ceil(total / 100) * 100
    })

    const recommendations = computed(() => {
      const rank = { increasing: 0, stable: 1, decreasing: 2 }
      const sorted = [...forecasts.value].sort((a, b) =>
        (rank[a.trend] - rank[b.trend]) ||
        ((b.forecasted_demand - b.current_demand) - (a.forecasted_demand - a.current_demand))
      )
      let remaining = budget.value
      const out = []
      for (const f of sorted) {
        const qty = Math.min(f.forecasted_demand, Math.floor(remaining / f.unit_cost))
        if (qty > 0) {
          out.push({
            sku: f.item_sku,
            name: f.item_name,
            quantity: qty,
            unit_price: f.unit_cost,
            lead_time_days: f.lead_time_days,
            trend: f.trend
          })
          remaining -= qty * f.unit_cost
        }
      }
      return out
    })

    const allocatedTotal = computed(() =>
      recommendations.value.reduce((sum, r) => sum + r.quantity * r.unit_price, 0)
    )

    const remainingBudget = computed(() => budget.value - allocatedTotal.value)

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
        console.error(err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (submitting.value || !recommendations.value.length) return
      submitting.value = true
      error.value = null
      successMessage.value = null
      try {
        // Send only sku + quantity; the server derives price/name/lead-time
        // from its own forecast catalog to prevent client-side tampering.
        const items = recommendations.value.map(r => ({ sku: r.sku, quantity: r.quantity }))
        const result = await api.createRestockingOrder({ budget: budget.value, items })
        successMessage.value = t('restocking.orderPlaced').replace('{orderNumber}', result.order_number)
      } catch (err) {
        error.value = 'Failed to place restocking order: ' + err.message
        console.error(err)
      } finally {
        submitting.value = false
      }
    }

    const getTrendClass = (trend) => {
      const map = {
        increasing: 'increasing',
        stable: 'stable',
        decreasing: 'decreasing'
      }
      return map[trend] || 'info'
    }

    onMounted(loadForecasts)

    return {
      t,
      currentCurrency,
      formatCurrency,
      forecasts,
      budget,
      loading,
      error,
      submitting,
      successMessage,
      maxBudget,
      recommendations,
      allocatedTotal,
      remainingBudget,
      placeOrder,
      getTrendClass
    }
  }
}
</script>

<style scoped>
.budget-display {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  margin: 1rem 0 1.25rem;
  accent-color: #2563eb;
  height: 6px;
  cursor: pointer;
  appearance: none;
  background: #e2e8f0;
  border-radius: 3px;
  outline: none;
}

.budget-slider::-webkit-slider-thumb {
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.budget-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-top: 0.5rem;
}

.empty-cell {
  text-align: center;
  color: #64748b;
  padding: 2rem;
  font-style: italic;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 0.875rem 1.25rem;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 500;
  margin-bottom: 1rem;
}

.btn-primary {
  background: #2563eb;
  color: #fff;
  border: none;
  padding: 0.75rem 2rem;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}
</style>
