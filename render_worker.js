const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const puppeteer = require('puppeteer');

function parseArgs() {
    const args = {};
    for (let i = 2; i < process.argv.length; i += 2) {
        const key = process.argv[i].replace(/^--/, '');
        args[key] = process.argv[i + 1];
    }
    return args;
}

async function run() {
    const args = parseArgs();
    const inputVideo = args.input;
    const transcriptPath = args.transcript;
    const outputPath = args.output;
    const presetName = args.preset || 'luca';

    if (!inputVideo || !transcriptPath || !outputPath) {
        throw new Error("Не переданы обязательные параметры (--input, --transcript, --output)");
    }

    if (!fs.existsSync(inputVideo)) throw new Error(`Видео не найдено: ${inputVideo}`);
    if (!fs.existsSync(transcriptPath)) throw new Error(`Транскрипт не найден: ${transcriptPath}`);

    const presetDir = path.join(__dirname, 'templates', presetName);
    const cssPath = path.join(presetDir, 'style.css');
    const configPath = path.join(presetDir, 'template.json');

    let cssContent = '';
    let fontLinksHTML = '';
    let templateConfig = {};

    if (fs.existsSync(presetDir)) {
        if (fs.existsSync(cssPath)) {
            cssContent = fs.readFileSync(cssPath, 'utf8');
        }
        if (fs.existsSync(configPath)) {
            try {
                templateConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
                if (templateConfig.fonts && Array.isArray(templateConfig.fonts)) {
                    fontLinksHTML = templateConfig.fonts.map(fontUrl => `<link rel="stylesheet" href="${fontUrl}">`).join('\n');
                } else if (templateConfig.font_url) {
                    fontLinksHTML = `<link rel="stylesheet" href="${templateConfig.font_url}">`;
                }
            } catch (e) {
                console.warn(`Предупреждение: Не удалось распарсить ${configPath}`);
            }
        }
    } else {
        throw new Error(`Шаблон "${presetName}" не найден по пути: ${presetDir}`);
    }

    if (!fontLinksHTML) {
        fontLinksHTML = `<link href="https://fonts.googleapis.com/css2?family=Anton&family=Caveat:wght@400..700&family=Bebas+Neue&family=Lobster&family=Montserrat:ital,wght@0,100..900;1,100..900&family=Poppins:wght@700;900&display=swap" rel="stylesheet">`;
    }

    let defaultVarsCSS = '';
    
    if (templateConfig.styleControls && Array.isArray(templateConfig.styleControls)) {
        templateConfig.styleControls.forEach(ctrl => {
            if (ctrl.id && ctrl.default !== undefined) {
                defaultVarsCSS += `--tscaps-${ctrl.id}: ${ctrl.default};\n`;
            }
        });
    }

    if (templateConfig.typography) {
        const t = templateConfig.typography;
        if (t.fontFamily) defaultVarsCSS += `--tscaps-font-family: '${t.fontFamily}';\n`;
        if (t.fontWeight) defaultVarsCSS += `--tscaps-font-weight: ${t.fontWeight};\n`;
        if (t.fontSize) defaultVarsCSS += `--tscaps-font-size: ${t.fontSize}cqh;\n`;
        if (t.letterSpacing !== undefined) defaultVarsCSS += `--tscaps-letter-spacing: ${t.letterSpacing}em;\n`;
        if (t.wordSpacing !== undefined) defaultVarsCSS += `--tscaps-word-spacing: ${t.wordSpacing}em;\n`;
        if (t.lineSpacing !== undefined) defaultVarsCSS += `--tscaps-line-spacing: ${t.lineSpacing}em;\n`;
    }

    const rawFontSize = args['font-size'];
    if (rawFontSize) {
        const userFontSize = /^\d+(\.\d+)?$/.test(String(rawFontSize)) ? `${rawFontSize}cqh` : String(rawFontSize);
        defaultVarsCSS += `--tscaps-font-size: ${userFontSize} !important;\n`;
    }

    const hAlign = args['h-align'] || args.h_align || args.halign || templateConfig.alignment?.horizontalAlign || 'center';
    defaultVarsCSS += `--tscaps-text-align: ${hAlign};\n`;

    const rawPosition = args['v-offset'] || args.position || (templateConfig.alignment?.verticalOffset !== undefined ? String(templateConfig.alignment.verticalOffset) : '0.8');
    let topPercent = 80;
    let translateY = '-50%';

    if (rawPosition === 'top') {
        topPercent = 15;
        translateY = '0%';
    } else if (rawPosition === 'center') {
        topPercent = 50;
        translateY = '-50%';
    } else if (rawPosition === 'bottom') {
        topPercent = 80;
        translateY = '-100%';
    } else {
        const num = parseFloat(rawPosition);
        if (!isNaN(num)) {
            topPercent = num <= 1 ? (num * 100) : num;
            translateY = '-50%';
        }
    }

    defaultVarsCSS += `--tscaps-v-offset: ${topPercent}%;\n--tscaps-position: ${rawPosition};\n--tscaps-h-align: ${hAlign};\n`;

    const rawTranscript = JSON.parse(fs.readFileSync(transcriptPath, 'utf8'));
    let wordsArray = [];
    if (Array.isArray(rawTranscript)) {
        wordsArray = rawTranscript;
    } else if (rawTranscript.words) {
        wordsArray = rawTranscript.words;
    } else if (rawTranscript.segments) {
        rawTranscript.segments.forEach(seg => {
            if (seg.words) wordsArray.push(...seg.words);
        });
    }

    const htmlContent = `
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        ${fontLinksHTML}
        <style>
            *, *::before, *::after { box-sizing: border-box !important; }
            :root { ${defaultVarsCSS} }
            html, body { width: 540px; height: 960px; margin: 0; padding: 0; background: transparent; overflow: hidden; }
            .scaler { width: 1080px; height: 1920px; transform: scale(0.5); transform-origin: 0 0; }
            .stage-wrapper { width: 1080px; height: 1920px; position: absolute; top: 0; left: 0; container-type: size; }
            #stage { width: 1080px !important; height: 1920px !important; position: absolute !important; left: 0 !important; top: 0 !important; margin: 0 !important; padding: 0 !important; }
            .subtitles-container { position: absolute !important; left: 110px !important; width: 860px !important; top: ${topPercent.toFixed(2)}% !important; transform: translateY(${translateY}) !important; box-sizing: border-box !important; }
            ${cssContent}
        </style>
    </head>
    <body class="tscaps preset-${presetName} ${presetName}">
        <div class="scaler">
            <div class="stage-wrapper tscaps preset-${presetName} ${presetName}">
                <div class="stage tscaps preset-${presetName} ${presetName}" id="stage"></div>
            </div>
        </div>
        <script>
            const rawWords = ${JSON.stringify(wordsArray)};
            const stage = document.getElementById('stage');
            const currentPreset = "${presetName}";
            const lineSplitterConfig = ${JSON.stringify(templateConfig.lineSplitter || { type: "fixed-tail", tailWordCount: 3 })};

            function buildSegments(wordList) {
                if (!wordList || wordList.length === 0) return [];
                const segments = [];
                let currentGroup = [];
                let segStart = wordList[0].start;

                for (let i = 0; i < wordList.length; i++) {
                    const w = wordList[i];
                    const prevW = wordList[i - 1];
                    const pause = prevW ? (w.start - prevW.end) : 0;
                    const charCount = currentGroup.reduce((acc, item) => acc + ((item.word || item.text || '').trim().length), 0);
                    const nextWordLen = (w.word || w.text || '').trim().length;

                    if (currentGroup.length > 0 && (pause > 0.4 || currentGroup.length >= 7 || (charCount + nextWordLen) > 30)) {
                        segments.push({
                            start: segStart,
                            end: prevW ? (prevW.end + 0.15) : w.start,
                            words: currentGroup,
                            isAfterPause: pause > 0.4
                        });
                        currentGroup = [];
                        segStart = w.start;
                    }
                    currentGroup.push(w);
                }
                if (currentGroup.length > 0) {
                    segments.push({
                        start: segStart,
                        end: currentGroup[currentGroup.length - 1].end + 0.25,
                        words: currentGroup,
                        isAfterPause: false
                    });
                }
                return segments;
            }

            function splitLines(segmentWords) {
                if (!segmentWords || segmentWords.length === 0) return [];
                const tailCount = lineSplitterConfig.tailWordCount || 3;
                if (lineSplitterConfig.type === 'fixed-tail' && segmentWords.length > tailCount) {
                    const line1 = segmentWords.slice(0, segmentWords.length - tailCount);
                    const line2 = segmentWords.slice(segmentWords.length - tailCount);
                    return [
                        { start: line1[0].start, end: line1[line1.length - 1].end, words: line1 },
                        { start: line2[0].start, end: line2[line2.length - 1].end, words: line2 }
                    ];
                }
                return [{ start: segmentWords[0].start, end: segmentWords[segmentWords.length - 1].end, words: segmentWords }];
            }

            const segments = buildSegments(rawWords);

            function renderTime(currentTime) {
                const segIdx = segments.findIndex(s => currentTime >= s.start && currentTime <= s.end);
                if (segIdx === -1) { stage.innerHTML = ''; return; }

                const seg = segments[segIdx];
                const segLines = splitLines(seg.words);
                const segOnStarts = (seg.start - currentTime).toFixed(4) + 's';
                const segOnEnds = (seg.end - currentTime).toFixed(4) + 's';
                const segDurStr = (seg.end - seg.start).toFixed(4) + 's';

                let segmentClasses = ['segment', 'section', currentPreset];
                if (segIdx === 0) segmentClasses.push('first-segment-in-document');
                if (seg.isAfterPause) segmentClasses.push('segment-after-pause');

                let html = '<div class="subtitles-container"><div class="' + segmentClasses.join(' ') + '" style="' +
                           '--on-segment-starts:' + segOnStarts + ';' +
                           '--on-segment-ends:' + segOnEnds + ';' +
                           '--segment-duration:' + segDurStr + ';' +
                           '">';

                segLines.forEach((line, lineIdx) => {
                    const lineOnStarts = (line.start - currentTime).toFixed(4) + 's';
                    const lineOnEnds = (line.end - currentTime).toFixed(4) + 's';
                    const lineDurStr = (line.end - line.start).toFixed(4) + 's';

                    let linePosClasses = [];
                    if (lineIdx === 0) linePosClasses.push('first-line-in-segment');
                    if (lineIdx === segLines.length - 1) linePosClasses.push('last-line-in-segment');

                    let lineStateClass = 'line-being-narrated';
                    if (currentTime < line.start) lineStateClass = 'line-not-narrated-yet';
                    else if (currentTime > line.end) lineStateClass = 'line-already-narrated';

                    html += '<div class="line ' + linePosClasses.join(' ') + ' ' + lineStateClass + '" style="' +
                            '--on-line-starts:' + lineOnStarts + ';' +
                            '--on-line-ends:' + lineOnEnds + ';' +
                            '--line-duration:' + lineDurStr + ';' +
                            '">';

                    line.words.forEach((w, wIdx) => {
                        const txt = (w.word || w.text || '').trim();
                        if (!txt) return;

                        let wordStateClass = 'word-being-narrated active';
                        if (currentTime < w.start) wordStateClass = 'word-not-narrated-yet';
                        else if (currentTime > w.end) wordStateClass = 'word-already-narrated';

                        const positionalClasses = [];
                        if (lineIdx === 0 && wIdx === 0) positionalClasses.push('first-word-in-segment');
                        if (wIdx === 0) positionalClasses.push('first-word-in-line');
                        if (wIdx === line.words.length - 1) positionalClasses.push('last-word-in-line');

                        const wOnStarts = (w.start - currentTime).toFixed(4) + 's';
                        const wOnEnds = (w.end - currentTime).toFixed(4) + 's';
                        const wDurStr = (w.end - w.start).toFixed(4) + 's';

                        html += '<span class="word ' + wordStateClass + ' ' + positionalClasses.join(' ') + '" ' +
                                'data-text="' + txt + '" ' +
                                'style="' +
                                '--word-char-count:' + txt.length + ';' +
                                '--on-word-starts:' + wOnStarts + ';' +
                                '--on-word-ends:' + wOnEnds + ';' +
                                '--word-duration:' + wDurStr + ';' +
                                '">' + txt + '</span>';
                    });
                    html += '</div>';
                });
                html += '</div></div>';
                stage.innerHTML = html;
            }
        </script>
    </body>
    </html>
    `;

    let browser;
    try {
        browser = await puppeteer.launch({
            headless: true,
            executablePath: process.env.CHROME_BIN || undefined,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-audio-output',
                '--js-flags=--max-old-space-size=128'
            ]
        });

        const page = await browser.newPage();
        // Уменьшенный viewport для снижения расхода RAM
        await page.setViewport({ width: 540, height: 960, deviceScaleFactor: 1 });
        await page.setContent(htmlContent, { waitUntil: 'domcontentloaded', timeout: 60000 });

        await page.evaluate(async () => {
            if (document.fonts) await document.fonts.ready;
        });

        const getDuration = () => new Promise((resolve, reject) => {
            const ffprobe = spawn('ffprobe', [
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                inputVideo
            ]);
            let out = '', err = '';
            ffprobe.stdout.on('data', data => out += data.toString());
            ffprobe.stderr.on('data', data => err += data.toString());
            ffprobe.on('close', code => {
                const dur = parseFloat(out.trim());
                if (code === 0 && !isNaN(dur)) resolve(dur);
                else reject(new Error(`ffprobe error (code ${code}): ${err}`));
            });
        });

        const duration = await getDuration();
        const fps = 30;
        const totalFrames = Math.ceil(duration * fps);

        // FFmpeg рендер с выборочным масштабированием кадра оверлея обратно до 1080x1920
        const ffmpeg = spawn('ffmpeg', [
            '-y',
            '-i', inputVideo,
            '-f', 'image2pipe',
            '-vcodec', 'png',
            '-r', `${fps}`,
            '-i', 'pipe:0',
            '-filter_complex', '[1:v]scale=1080:1920[sub];[0:v][sub]overlay=0:0:shortest=1[outv]',
            '-map', '[outv]',
            '-map', '0:a?',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '26',
            '-c:a', 'copy',
            outputPath
        ]);

        const writeFrameToFFmpeg = (buffer) => {
            return new Promise((resolve) => {
                const canContinue = ffmpeg.stdin.write(buffer);
                if (canContinue) {
                    resolve();
                } else {
                    ffmpeg.stdin.once('drain', resolve);
                }
            });
        };

        for (let frame = 0; frame < totalFrames; frame++) {
            const currentTime = frame / fps;
            await page.evaluate((t) => renderTime(t), currentTime);

            const screenshotBuffer = await page.screenshot({
                type: 'png',
                omitBackground: true
            });

            await writeFrameToFFmpeg(screenshotBuffer);
        }

        ffmpeg.stdin.end();

        await new Promise((resolve, reject) => {
            ffmpeg.on('close', code => {
                if (code === 0) resolve();
                else reject(new Error(`FFmpeg error code: ${code}`));
            });
        });

        console.log(`Рендеринг завершен: ${outputPath}`);
    } finally {
        if (browser) {
            await browser.close();
        }
    }
}

run().catch(err => {
    console.error("ОШИБКА РЕНДЕРЕРА:", err.stack || err.message || err);
    process.exit(1);
});