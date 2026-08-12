import { 
    RenderPipelineBuilder, 
    PassthroughTranscriber,
    LimitByWordsSegmentSplitter,
    BalancedLineSplitter 
} from '@tscaps/engine';

window.initTscapsEngine = async function(wordsArray, cssContent, templateConfig) {
    // 1. Формируем первичный Document для PassthroughTranscriber
    const doc = {
        sections: [{
            kind: 'default',
            segments: [{
                start: wordsArray[0]?.start || 0,
                end: wordsArray[wordsArray.length - 1]?.end || 0,
                lines: [{
                    words: wordsArray.map(w => ({
                        text: w.word || w.text || '',
                        start: w.start,
                        end: w.end
                    }))
                }]
            }]
        }]
    };

    // 2. Инициализируем пайплайн движка
    const builder = new RenderPipelineBuilder()
        .withTranscriber(new PassthroughTranscriber(doc))
        .withCss(cssContent);

    // Если в template.json есть параметры сплиттера — применяем их
    if (templateConfig?.segment_splitter) {
        builder.withDefaultSegmentSplitterConfig(templateConfig.segment_splitter);
    }
    if (templateConfig?.line_splitter) {
        builder.withDefaultLineSplitterConfig(templateConfig.line_splitter);
    }

    const pipeline = builder.build();

    // 3. Выполняем этапы подготовки (транскрипция, сплиттинг, тегирование)
    await pipeline.runTranscriptionStep();
    await pipeline.runSplittingStep();
    await pipeline.runStructuralTaggingStep();
    await pipeline.runSemanticTaggingStep();

    window.tscapsPipeline = pipeline;
};

window.renderTscapsFrame = async function(currentTime) {
    if (!window.tscapsPipeline) return;
    // Отрисовка кадра встроенным фрейм-рендерером движка
    await window.tscapsPipeline.renderFrameAt(currentTime);
};

// Безопасная функция сохранения для WebApp (обходит ошибку string did not Match pattern)
window.saveAndRender = async function(sessionId, updatedWords, currentPreset) {
    try {
        if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.MainButton.showProgress();
        }

        const response = await fetch('/api/render', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                words: updatedWords,
                preset: currentPreset
            })
        });

        if (!response.ok) {
            throw new Error(`Ошибка сервера: ${response.statusText}`);
        }

        if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.close();
        }
    } catch (err) {
        console.error("Ошибка при сохранении:", err);
        alert("Не удалось запустить монтирование: " + err.message);
        if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.MainButton.hideProgress();
        }
    }
};