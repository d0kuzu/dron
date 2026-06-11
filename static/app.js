document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('refresh-btn');
    const btnText = refreshBtn.querySelector('.btn-text');
    const loader = refreshBtn.querySelector('.loader');
    const lastUpdatedEl = document.getElementById('last-updated');
    
    const confirmDialog = document.getElementById('confirm-dialog');
    const confirmBtn = document.getElementById('confirm-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    
    const matchedCards = document.getElementById('matched-cards');
    const excludedCards = document.getElementById('excluded-cards');
    
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    // Tabs logic
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(btn.dataset.target).classList.add('active');
        });
    });

    // Formatting date
    function formatDate(isoString) {
        if (!isoString) return 'Неизвестно';
        const date = new Date(isoString);
        return new Intl.DateTimeFormat('ru-RU', {
            day: 'numeric', month: 'long', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        }).format(date);
    }

    // Creating Card HTML
    function createCard(item) {
        const score = item.match_analysis?.total_score ?? 0;
        const reasons = item.match_analysis?.reasons || [];
        
        const reasonsHtml = reasons.length > 0 
            ? `<div class="reasons-list">
                <strong>Причины:</strong>
                <ul>${reasons.map(r => `<li>${r}</li>`).join('')}</ul>
               </div>` 
            : '';

        return `
            <div class="card">
                <div class="card-header">
                    <div class="card-title">${item.title || 'Без названия'}</div>
                    <div class="score-badge">Счет: ${score}</div>
                </div>
                <div class="card-body">
                    <div class="info-row">
                        <span class="info-label">Агентство:</span>
                        <span class="info-value">${item.department_bucket || item.agency || 'Н/Д'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Дедлайн:</span>
                        <span class="info-value">${item.response_deadline || 'Н/Д'}</span>
                    </div>
                    ${reasonsHtml}
                </div>
                <div class="card-footer">
                    <a href="${item.sam_link}" target="_blank" class="link-btn">Открыть на SAM.gov</a>
                </div>
            </div>
        `;
    }

    // Render data
    function renderData(data) {
        const matched = data.matched?.opportunities || [];
        const excluded = data.excluded?.opportunities || [];
        const generatedAt = data.matched?.generated_at;

        if (generatedAt) {
            lastUpdatedEl.textContent = `Последний запуск: ${formatDate(generatedAt)}`;
        }

        matchedCards.innerHTML = matched.length > 0 
            ? matched.map(createCard).join('') 
            : '<p class="subtitle">Нет подходящих заказов</p>';
            
        excludedCards.innerHTML = excluded.length > 0 
            ? excluded.map(createCard).join('') 
            : '<p class="subtitle">Нет отклоненных заказов</p>';
    }

    // Fetch initial data
    async function loadData() {
        try {
            const res = await fetch('/api/data');
            if (!res.ok) throw new Error('Ошибка сети');
            const data = await res.json();
            renderData(data);
        } catch (error) {
            console.error('Ошибка загрузки данных:', error);
            lastUpdatedEl.textContent = 'Ошибка загрузки данных. Убедитесь, что файлы существуют.';
        }
    }

    // Refresh action
    refreshBtn.addEventListener('click', () => {
        confirmDialog.classList.remove('hidden');
    });

    cancelBtn.addEventListener('click', () => {
        confirmDialog.classList.add('hidden');
    });

    confirmBtn.addEventListener('click', async () => {
        confirmDialog.classList.add('hidden');
        
        // UI loading state
        refreshBtn.disabled = true;
        btnText.textContent = 'Обработка...';
        loader.classList.remove('hidden');
        lastUpdatedEl.textContent = 'Скрипт выполняется, пожалуйста подождите...';
        
        try {
            const res = await fetch('/api/refresh', { method: 'POST' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Ошибка выполнения');
            }
            const data = await res.json();
            renderData(data);
        } catch (error) {
            console.error('Ошибка при обновлении:', error);
            
            const errorStr = error.message.toLowerCase();
            if (errorStr.includes('429') || errorStr.includes('throttled') || errorStr.includes('quota') || errorStr.includes('too many requests')) {
                alert('Лимит запросов исчерпан! SAM.gov временно заблокировал доступ (обычно до следующего дня). На экране остались старые данные.');
                await loadData(); 
                lastUpdatedEl.textContent = 'Внимание: Достигнут суточный лимит запросов SAM.gov';
                lastUpdatedEl.style.color = 'var(--danger-color)';
            } else {
                alert(`Произошла ошибка: ${error.message}`);
                await loadData(); // Revert to old data
            }
        } finally {
            refreshBtn.disabled = false;
            btnText.textContent = 'Загрузить новые';
            loader.classList.add('hidden');
        }
    });

    // Init
    loadData();
});
