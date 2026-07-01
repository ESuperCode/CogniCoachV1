const muscleCheckboxIds = [
            'biceps', 'deltoids', 'forearms', 'triceps',
            'trapezius', 'lats',
            'abs', 'obliques', 'pectorals',
            'adductors', 'calves', 'hamstrings', 'glutes', 'quads'
        ];

        // Global drills list: array of strings in the form "drillname + description"
        window.globalDrillsList = [];

        function updateGlobalDrillsList(drillData) {
            if (!drillData) return;
            const name = drillData.name || drillData.Name || 'Drill';
            const desc = drillData.description || drillData.Description || '';
            const entry = `${name} + ${desc}`;
            if (!window.globalDrillsList.includes(entry)) {
                window.globalDrillsList.push(entry);
            }
        }

        const muscleSvgGroupIds = {
            biceps: 'Biceps',
            deltoids: 'Deltoids',
            forearms: 'Forearms',
            triceps: 'Triceps',
            trapezius: 'Trapezius',
            lats: 'Lats',
            abs: 'Abs',
            obliques: 'Obliques',
            pectorals: 'Pectorals',
            adductors: 'Adductors',
            calves: 'Calves',
            hamstrings: 'Hamstrings',
            glutes: 'Glutes',
            quads: 'Quads'
        };

        async function loadMuscleDiagram() {
            const container = document.getElementById('muscleSvgHost');
            if (!container) {
                return;
            }

            try {
                const response = await fetch('assets/muscle-diagram.svg');
                if (!response.ok) {
                    throw new Error(`Unable to load muscle diagram (${response.status})`);
                }

                container.innerHTML = await response.text();
            } catch (error) {
                console.error('Failed to load muscle diagram:', error);
                container.innerHTML = '<p class="text-muted">Unable to load muscle diagram.</p>';
            }
        }

        // State Management
        let appState = {
            setup: {
                sport: '',
                location: '',
                focus: '',
                muscleGroup: '',
                level: 'intermediate',
                workoutLength: 60,
                sections: [
                    { name: 'Warm Up', color: '#FFD700' },
                    { name: 'Main Work', color: '#FF6347' },
                    { name: 'Cool Down', color: '#4682B4' },
                    { name: 'Recovery', color: '#32CD32' }
                ],
                timeline: []
            },
            session: {
                currentDrillIndex: 0,
                drills: [],
                timerInterval: null,
                timeRemaining: 0,
                totalTime: 0,
                isPaused: false,
                timerStarted: false
            }
        };

        function applySportPresetFromQuery() {
            const params = new URLSearchParams(window.location.search);
            const sport = params.get('sport');
            const location = params.get('location');
            const focus = params.get('focus');
            const workoutLength = params.get('workoutLength');

            if (sport) {
                const sportInput = document.getElementById('sport');
                if (sportInput) {
                    sportInput.value = sport;
                }
            }

            if (location) {
                const locationInput = document.getElementById('location');
                if (locationInput) {
                    locationInput.value = location;
                }
            }

            if (focus) {
                const focusInput = document.getElementById('focus');
                if (focusInput) {
                    focusInput.value = focus;
                }
            }

            if (workoutLength) {
                const workoutLengthInput = document.getElementById('workoutLength');
                if (workoutLengthInput) {
                    workoutLengthInput.value = workoutLength;
                }
                updateSliderValue();
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initializeInteractiveBackground();
            
            loadState();

            const params = new URLSearchParams(window.location.search);
            const details = document.querySelector('.seo-section');
            if (details && details.hasAttribute('open')) {
                details.removeAttribute('open');
            }

            applySportPresetFromQuery();
            initializeColorLegend();
            initializeTimeline();
            updateSliderValue();
            loadMuscleDiagram().then(() => initializeMuscleDiagramInteractions());
            
            // Update slider value on change
            document.getElementById('workoutLength').addEventListener('input', updateSliderValue);

            // Ensure Skip-to-End button exists next to the start button
            const startBtn = document.getElementById('startTimerBtn');
            if (startBtn) {
                let skipBtn = document.getElementById('skipToEndBtn');
                if (!skipBtn) {
                    skipBtn = document.createElement('button');
                    skipBtn.id = 'skipToEndBtn';
                    skipBtn.className = 'btn btn-secondary';
                    skipBtn.style.display = 'none';
                    skipBtn.style.marginLeft = '8px';
                    skipBtn.textContent = 'Skip to End';
                    skipBtn.addEventListener('click', skipToEnd);
                    startBtn.parentNode.insertBefore(skipBtn, startBtn.nextSibling);
                }
            }
        });

        function initializeInteractiveBackground() {
            const root = document.documentElement;
            const updatePointer = (clientX, clientY) => {
                const x = Math.max(0, Math.min(100, (clientX / window.innerWidth) * 100));
                const y = Math.max(0, Math.min(100, (clientY / window.innerHeight) * 100));
                const dx = (x - 50) / 50;
                const dy = (y - 50) / 50;

                const shiftX = (dx * -3).toFixed(2) + 'px';
                const shiftY = (dy * -3).toFixed(2) + 'px';
                const gridOffsetX = (dx * -8).toFixed(2) + 'px';
                const gridOffsetY = (dy * -8).toFixed(2) + 'px';
                const rotateX = (dy * -14).toFixed(2) + 'deg';
                const rotateY = (dx * 14).toFixed(2) + 'deg';
                const scale = (1 + Math.abs(dx) * 0.03 + Math.abs(dy) * 0.03).toFixed(2);
                const bgRotateX = (dy * -8).toFixed(2) + 'deg';
                const bgRotateY = (dx * 8).toFixed(2) + 'deg';
                const bgScale = (1 + Math.abs(dx) * 0.02 + Math.abs(dy) * 0.02).toFixed(2);

                root.style.setProperty('--pointer-x', x.toFixed(2) + '%');
                root.style.setProperty('--pointer-y', y.toFixed(2) + '%');
                root.style.setProperty('--bg-shift-x', shiftX);
                root.style.setProperty('--bg-shift-y', shiftY);
                root.style.setProperty('--grid-shift-x', gridOffsetX);
                root.style.setProperty('--grid-shift-y', gridOffsetY);
                root.style.setProperty('--grid-offset-x', gridOffsetX);
                root.style.setProperty('--grid-offset-y', gridOffsetY);
                root.style.setProperty('--grid-rotate-x', rotateX);
                root.style.setProperty('--grid-rotate-y', rotateY);
                root.style.setProperty('--grid-scale', scale);
                root.style.setProperty('--bg-rotate-x', bgRotateX);
                root.style.setProperty('--bg-rotate-y', bgRotateY);
                root.style.setProperty('--bg-scale', bgScale);
            };

            window.addEventListener('pointermove', event => {
                updatePointer(event.clientX, event.clientY);
            }, { passive: true });

            window.addEventListener('touchmove', event => {
                const touch = event.touches && event.touches[0];
                if (touch) {
                    updatePointer(touch.clientX, touch.clientY);
                }
            }, { passive: true });
        }
        // Update slider display
        function updateSliderValue() {
            const slider = document.getElementById('workoutLength');
            const value = document.getElementById('workoutLengthValue');
            value.textContent = slider.value + ' min';
        }

        // Initialize color legend
        function initializeColorLegend() {
            const legend = document.getElementById('colorLegend');
            legend.innerHTML = '';
            
            appState.setup.sections.forEach((section, index) => {
                const item = document.createElement('div');
                item.className = 'legend-item';
                item.innerHTML = `
                    <div class="color-picker-wrapper">
                        <input type="color" value="${section.color}" onchange="updateSectionColor(${index}, this.value)">
                        <input type="text" class="legend-label" value="${section.name}" onchange="updateSectionName(${index}, this.value)">
                    </div>
                `;
                legend.appendChild(item);
            });
        }

        // Update section color
        function updateSectionColor(index, color) {
            appState.setup.sections[index].color = color;
            updateTimelineColors();
            saveState();
        }

        // Update section name
        function updateSectionName(index, name) {
            appState.setup.sections[index].name = name;
            renderDrillBank();
            saveState();
        }

        // Initialize timeline and drill bank
        function initializeTimeline() {
            renderDrillBank();
            renderTimeline();
        }

        function clearCurrentWorkoutData() {
            appState.setup.timeline = [];
            appState.session.drills = [];
            appState.session.currentDrillIndex = 0;
            appState.session.timerInterval = null;
            appState.session.timeRemaining = 0;
            appState.session.totalTime = 0;
            appState.session.isPaused = false;
            appState.session.timerStarted = false;
            renderTimeline();
            saveState();
        }

        function useDefaultWorkout() {
            appState.setup.timeline = [
                { section: 0, id: 'drill-' + Date.now() + '-1' },
                { section: 0, id: 'drill-' + Date.now() + '-2' },
                { section: 1, id: 'drill-' + Date.now() + '-3' },
                { section: 1, id: 'drill-' + Date.now() + '-4' },
                { section: 1, id: 'drill-' + Date.now() + '-5' },
                { section: 1, id: 'drill-' + Date.now() + '-6' },
                { section: 2, id: 'drill-' + Date.now() + '-7' },
                { section: 3, id: 'drill-' + Date.now() + '-8' }
            ];
            renderTimeline();
            saveState();
        }

        // Render timeline
        function renderTimeline() {
            const timeline = document.getElementById('timelineBar');
            timeline.innerHTML = '';

            if (appState.setup.timeline.length === 0) {
                const emptyState = document.createElement('div');
                emptyState.className = 'timeline-empty';
                emptyState.textContent = 'Drag section squares here to build your workout timeline.';
                timeline.appendChild(emptyState);
                return;
            }

            appState.setup.timeline.forEach((drill) => {
                const square = createDrillSquare(drill);
                timeline.appendChild(square);
            });
        }

        function renderDrillBank() {
            const bank = document.getElementById('drillBank');
            bank.innerHTML = '';

            appState.setup.sections.forEach((section, index) => {
                const square = document.createElement('div');
                square.className = 'drill-square';
                square.draggable = true;
                square.id = `bank-section-${index}`;
                square.dataset.source = 'bank';
                square.dataset.section = index;
                square.dataset.label = section.name;
                square.style.backgroundColor = section.color;
                square.textContent = section.name.charAt(0).toUpperCase();
                square.ondragstart = drag;
                bank.appendChild(square);
            });
        }

        // Create drill square
        function createDrillSquare(drill) {
            const square = document.createElement('div');
            square.className = 'drill-square';
            square.draggable = true;
            square.id = drill.id;
            square.dataset.source = 'timeline';
            square.dataset.section = drill.section;
            square.style.backgroundColor = appState.setup.sections[drill.section].color;
            square.ondragstart = drag;
            return square;
        }

        function clearTimeline() {
            appState.setup.timeline = [];
            renderTimeline();
            saveState();
        }

        function getDropInsertIndex(dropTarget, event) {
            if (!dropTarget) {
                return appState.setup.timeline.length;
            }

            const timelineSquares = Array.from(document.querySelectorAll('#timelineBar .drill-square'));
            const targetIndex = timelineSquares.indexOf(dropTarget);
            const rect = dropTarget.getBoundingClientRect();
            const insertBeforeTarget = event.clientX < rect.left + (rect.width / 2);

            return insertBeforeTarget ? targetIndex : targetIndex + 1;
        }

        // Drag and drop functions
        function allowDrop(ev) {
            ev.preventDefault();
        }

        function drag(ev) {
            ev.dataTransfer.setData("text", ev.target.id);
            ev.dataTransfer.setData("source", ev.target.dataset.source || 'timeline');
            ev.dataTransfer.setData("section", ev.target.dataset.section || '');
            ev.target.classList.add('dragging');
        }

        function drop(ev) {
            ev.preventDefault();
            const data = ev.dataTransfer.getData("text");
            const source = ev.dataTransfer.getData("source");
            const section = ev.dataTransfer.getData("section");
            const draggedElement = document.getElementById(data);
            const dropTarget = ev.target.closest('.drill-square');
            const droppedInTimeline = ev.target.id === 'timelineBar' || ev.target.closest('#timelineBar');
            const droppedInTrash = ev.target.id === 'trashBin' || ev.target.closest('#trashBin');

            if (draggedElement) {
                draggedElement.classList.remove('dragging');
            }

            if (droppedInTrash) {
                if (source === 'timeline') {
                    appState.setup.timeline = appState.setup.timeline.filter(drill => drill.id !== data);
                    renderTimeline();
                    saveState();
                }
                return;
            }

            if (!droppedInTimeline) {
                return;
            }

            if (source === 'bank') {
                const newDrill = {
                    section: parseInt(section, 10),
                    id: 'drill-' + Date.now() + '-' + Math.floor(Math.random() * 10000)
                };

                if (dropTarget && dropTarget.dataset.source === 'timeline') {
                    const insertIndex = getDropInsertIndex(dropTarget, ev);
                    appState.setup.timeline.splice(insertIndex, 0, newDrill);
                } else {
                    appState.setup.timeline.push(newDrill);
                }

                renderTimeline();
                saveState();
                return;
            }

            if (source === 'timeline' && draggedElement) {
                const draggedIndex = appState.setup.timeline.findIndex(drill => drill.id === data);
                if (draggedIndex === -1) {
                    return;
                }

                const [movedDrill] = appState.setup.timeline.splice(draggedIndex, 1);

                if (dropTarget && dropTarget !== draggedElement && dropTarget.dataset.source === 'timeline') {
                    let insertIndex = getDropInsertIndex(dropTarget, ev);
                    const targetIndexAfterRemoval = appState.setup.timeline.findIndex(drill => drill.id === dropTarget.id);

                    if (targetIndexAfterRemoval !== -1 && insertIndex > targetIndexAfterRemoval + 1) {
                        insertIndex = targetIndexAfterRemoval + 1;
                    }

                    appState.setup.timeline.splice(insertIndex, 0, movedDrill);
                } else {
                    appState.setup.timeline.push(movedDrill);
                }

                renderTimeline();
                saveState();
            }
        }

        // Update timeline colors
        function updateTimelineColors() {
            renderDrillBank();

            const squares = document.querySelectorAll('#timelineBar .drill-square');
            squares.forEach(square => {
                const drill = appState.setup.timeline.find(d => d.id === square.id);
                if (drill) {
                    square.style.backgroundColor = appState.setup.sections[drill.section].color;
                }
            });
        }

        // Start session
        function startSession() {
            const hasCurrentWorkoutData = appState.setup.timeline.length > 0 || appState.session.drills.length > 0;

            if (hasCurrentWorkoutData) {
                const shouldClear = confirm('This will clear any current workout data. Continue?');
                if (!shouldClear) {
                    return;
                }
                clearCurrentWorkoutData();
            }

            // Collect form data
            appState.setup.sport = document.getElementById('sport').value || 'General';
            appState.setup.location = document.getElementById('location').value || 'Any';
            appState.setup.focus = document.getElementById('focus').value || 'General';
            appState.setup.muscleGroup = document.getElementById('muscleGroup').value || 'Full Body';
            appState.setup.level = document.getElementById('level').value;
            appState.setup.workoutLength = parseInt(document.getElementById('workoutLength').value);

            // Validate
            if (appState.setup.timeline.length === 0) {
                alert('Please add at least one drill to your workout!');
                return;
            }

            // Calculate drill times (smart, human-friendly distribution)
            const totalSeconds = appState.setup.workoutLength * 60;
            const drillCount = appState.setup.timeline.length;

            const times = computeDrillTimes(totalSeconds, drillCount);

            // Prepare drills
            appState.session.drills = appState.setup.timeline.map((drill, index) => ({
                ...drill,
                drillTime: times[index] || Math.max(5, Math.floor(totalSeconds / Math.max(1, drillCount))),
                sectionName: appState.setup.sections[drill.section].name,
                generatedDrill: null
            }));

            appState.session.currentDrillIndex = 0;

            // Show session view
            document.getElementById('setupView').style.display = 'none';
            document.getElementById('sessionView').classList.add('active');

            // Load first drill
            loadCurrentDrill();
            saveState();
        }

        // Load current drill
        async function loadCurrentDrill() {
            const drill = appState.session.drills[appState.session.currentDrillIndex];
            
            // Show loading
            document.getElementById('loadingContainer').classList.add('active');
            document.getElementById('drillContent').classList.add('hidden');

            // Prepare data for getDrill
            const drillRequest = {
                sport: appState.setup.sport,
                focus: appState.setup.focus,
                "muscle group": appState.setup.muscleGroup,
                level: appState.setup.level,
                "drill time": drill.drillTime,
                section: drill.sectionName,
                location:appState.setup.location
            };

            try {
                const drillData = drill.generatedDrill
                    ? normalizeDrillData(
                        typeof drill.generatedDrill === 'string'
                            ? parseDrillResponse(drill.generatedDrill)
                            : drill.generatedDrill
                    )
                    : await getDrill(drillRequest);

                if (!drill.generatedDrill) {
                    appState.session.drills[appState.session.currentDrillIndex].generatedDrill = drillData;
                    saveState();
                }

                renderDrill(drill, drillData);

            } catch (error) {
                console.error('Error loading drill:', error);
                // Show error state
                document.getElementById('loadingContainer').classList.remove('active');
                document.getElementById('drillContent').classList.remove('hidden');
                document.getElementById('drillName').textContent = 'Error Loading Drill';
                document.getElementById('drillDescription').textContent = 'There was an error loading the drill. Please try again.';
                document.getElementById('timerStatus').textContent = 'Unable to load the drill.';
            }
        }

        async function getDrill(drillRequest) {
            const temperatureInput = document.getElementById("temperature").value;
            const temperature = Number(temperatureInput);
            const requestBody = {
                    model: "zai-glm-4.7",
                    messages: [{role: 'system', content: 'You are a fitness coach that creates workout drills based on user preferences. Only respond with JSON formatted as {name: string,description: string,targeted muscles:[list],focus: string }. Make the drill unique creative, and completley new tailored specifically to the users needs the description should be a detailed explanation of the drill telling the user exactly how to preform the exersize eg. move your arms in a circular motion, rapidly extend your leg etc.'},
                {role: 'user', content: `Create a ${drillRequest.section} drill for a ${drillRequest.level} athlete who is practicing at ${drillRequest.location} they want to focus on ${drillRequest.focus} and want to work their ${drillRequest["muscle group"]}, the drill should take exactly ${drillRequest["drill time"]}. The drill should should include certain movements that are conventional and specific for the task at hand. The drill should be easy to understand fr the user and should make logical sense and be easy to follow. Make sure the drill builds upod but is really different from these drills: ${window.globalDrillsList} if none are provided dont worry`}
                ]
            };

            if (Number.isFinite(temperature)) {
                requestBody.temperature = temperature;
            }

            console.log('Drill request:', drillRequest);         
            try {
                const response = await fetch("https://api.cerebras.ai/v1/chat/completions", {
                method: "POST",
                headers: {
                    "Authorization": "Bearer csk-4ecm9mj5wfrmy986h92jtrcx6y8pcjxw9fk3n4yndp528ynd",
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(requestBody)
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Cerebras API error ${response.status}: ${errorText}`);
                }
                
                const result = await response.json();
            const content = result?.choices?.[0]?.message?.content;
            console.log(content);
            return normalizeDrillData(parseDrillResponse(content));
            } catch (error) {
                console.error("Cerebras Request Failed:", error);
                throw error;
            }
            
            
           
            
            
        }
       
        function parseDrillResponse(content) {
            if (typeof content === 'object' && content !== null) {
                return content;
            }

            const rawContent = String(content || '').trim();
            const withoutCodeFence = rawContent
                .replace(/^```json\s*/i, '')
                .replace(/^```\s*/i, '')
                .replace(/\s*```$/i, '')
                .trim();

            try {
                return JSON.parse(withoutCodeFence);
            } catch (error) {
                const objectStart = withoutCodeFence.indexOf('{');
                const objectEnd = withoutCodeFence.lastIndexOf('}');

                if (objectStart !== -1 && objectEnd !== -1 && objectEnd > objectStart) {
                    return JSON.parse(withoutCodeFence.slice(objectStart, objectEnd + 1));
                }

                throw error;
            }
        }

        function normalizeDrillData(drillData) {
            const normalizedTargetedMuscles =
                drillData?.["targeted muscles"] ||
                drillData?.targetedMuscles ||
                drillData?.targeted_muscles ||
                [];

            return {
                name: drillData?.name || drillData?.Name || 'Drill',
                description: drillData?.description || drillData?.Description || 'No description provided.',
                focus: drillData?.focus || drillData?.Focus || appState.setup.focus || 'General',
                "targeted muscles": Array.isArray(normalizedTargetedMuscles)
                    ? normalizedTargetedMuscles
                    : String(normalizedTargetedMuscles)
                        .split(',')
                        .map(item => item.trim())
                        .filter(Boolean)
            };
        }

        function renderDrill(drill, drillData) {
            document.getElementById('loadingContainer').classList.remove('active');
            document.getElementById('drillContent').classList.remove('hidden');

            document.getElementById('currentDrill').textContent = appState.session.currentDrillIndex + 1;
            document.getElementById('totalDrills').textContent = appState.session.drills.length;
            document.getElementById('drillName').textContent = drillData.name || 'Drill';
            document.getElementById('drillDescription').textContent = drillData.description || 'No description provided.';
            document.getElementById('drillFocus').textContent = 'Focus: ' + (drillData.focus || appState.setup.focus);

            highlightMuscles(drillData["targeted muscles"] || []);
            // Add this drill to the global drills list (name + description)
            updateGlobalDrillsList(drillData);
            prepareTimer(drill.drillTime);
        }

        
        function highlightMuscles(muscles) {
            const muscleAliases = {
                abdominal: 'abs',
                abdominals: 'abs',
                abs: 'abs',
                core: 'abs',
                chest: 'pectorals',
                pecs: 'pectorals',
                pectoral: 'pectorals',
                pectorals: 'pectorals',
                shoulder: 'deltoids',
                shoulders: 'deltoids',
                delt: 'deltoids',
                delts: 'deltoids',
                deltoid: 'deltoids',
                deltoids: 'deltoids',
                bicep: 'biceps',
                biceps: 'biceps',
                tricep: 'triceps',
                triceps: 'triceps',
                forearm: 'forearms',
                forearms: 'forearms',
                lat: 'lats',
                lats: 'lats',
                latissimus: 'lats',
                "latissimus dorsi": 'lats',
                trapezius: 'trapezius',
                trap: 'trapezius',
                traps: 'trapezius',
                oblique: 'obliques',
                obliques: 'obliques',
                quad: 'quads',
                quads: 'quads',
                quadricep: 'quads',
                quadriceps: 'quads',
                hamstring: 'hamstrings',
                hamstrings: 'hamstrings',
                calf: 'calves',
                calves: 'calves',
                glute: 'glutes',
                glutes: 'glutes',
                gluteus: 'glutes',
                adductor: 'adductors',
                adductors: 'adductors'
            };

            resetMuscleSelections();

            const muscleList = Array.isArray(muscles)
                ? muscles
                : String(muscles || '')
                    .split(',')
                    .map(item => item.trim())
                    .filter(Boolean);

            const matchedIds = new Set();

            muscleList.forEach(muscle => {
                const normalizedMuscle = String(muscle)
                    .toLowerCase()
                    .replace(/[^\w\s-]/g, '')
                    .trim();

                if (!normalizedMuscle) {
                    return;
                }

                const directMatch = muscleCheckboxIds.find(id => normalizedMuscle === id);
                const aliasMatch = muscleAliases[normalizedMuscle];
                const phraseAliasKey = Object.keys(muscleAliases).find(alias => normalizedMuscle.includes(alias));
                const phraseAliasMatch = phraseAliasKey ? muscleAliases[phraseAliasKey] : null;
                const partialMatch = muscleCheckboxIds.find(id => normalizedMuscle.includes(id) || id.includes(normalizedMuscle));
                const resolvedId = directMatch || aliasMatch || phraseAliasMatch || partialMatch;

                if (resolvedId) {
                    matchedIds.add(resolvedId);
                }
            });

            matchedIds.forEach(id => {
                const input = document.getElementById(id);
                if (input) {
                    input.dataset.aiSelected = 'true';
                    input.dataset.manualSelected = 'false';
                    syncMuscleSelectionState(id);
                }
            });
        }

        function resetMuscleSelections() {
            muscleCheckboxIds.forEach(id => {
                const input = document.getElementById(id);
                if (!input) {
                    return;
                }

                input.checked = false;
                input.disabled = false;
                input.dataset.aiSelected = 'false';
                input.dataset.manualSelected = 'false';
                syncMuscleSelectionState(id);
            });
        }

        function syncMuscleSelectionState(id) {
            const input = document.getElementById(id);
            const label = document.querySelector(`.muscle-groups label[for="${id}"]`);
            const groupId = muscleSvgGroupIds[id];
            const svgGroup = groupId
                ? document.querySelector(`.muscle-groups #muscleSvgHost svg g g[id="${groupId}"]`)
                : null;

            if (!input) {
                return;
            }

            const isAiSelected = input.dataset.aiSelected === 'true';
            const isManualSelected = input.dataset.manualSelected === 'true';

            input.checked = isAiSelected;
            input.disabled = isAiSelected;

            if (label) {
                label.classList.toggle('ai-selected', isAiSelected);
                label.classList.toggle('manual-selected', isManualSelected);
            }

            if (svgGroup) {
                svgGroup.classList.toggle('ai-selected', isAiSelected);
                svgGroup.classList.toggle('manual-selected', isManualSelected);
            }
        }

        function toggleManualMuscle(id) {
            const input = document.getElementById(id);
            if (!input) {
                return;
            }

            const isManualSelected = input.dataset.manualSelected === 'true';
            input.dataset.manualSelected = isManualSelected ? 'false' : 'true';
            syncMuscleSelectionState(id);
        }

        function prepareTimer(seconds) {
            if (appState.session.timerInterval) {
                clearInterval(appState.session.timerInterval);
            }

            appState.session.timerInterval = null;
            appState.session.totalTime = seconds;
            appState.session.timeRemaining = seconds;
            appState.session.isPaused = false;
            appState.session.timerStarted = false;

            document.getElementById('nextDrillContainer').style.display = 'none';
            document.getElementById('startTimerBtn').style.display = 'inline-block';
            const skipBtnEl = document.getElementById('skipToEndBtn');
            if (skipBtnEl) skipBtnEl.style.display = 'inline-block';
            document.getElementById('pauseBtn').textContent = 'Pause';
            document.getElementById('pauseBtn').disabled = true;
            document.getElementById('timerStatus').textContent = 'Drill loaded. Start when you are ready.';

            updateTimerDisplay();
            saveState();
        }

        // Start timer
        function startTimer() {
            if (appState.session.timerStarted) {
                return;
            }

            if (appState.session.timerInterval) {
                clearInterval(appState.session.timerInterval);
            }

            appState.session.isPaused = false;
            appState.session.timerStarted = true;

            document.getElementById('nextDrillContainer').style.display = 'none';
            document.getElementById('startTimerBtn').style.display = 'none';
            document.getElementById('pauseBtn').textContent = 'Pause';
            document.getElementById('pauseBtn').disabled = false;
            document.getElementById('timerStatus').textContent = 'Timer is running.';

            updateTimerDisplay();

            appState.session.timerInterval = setInterval(() => {
                if (!appState.session.isPaused) {
                    appState.session.timeRemaining--;

                    updateTimerDisplay();

                    if (appState.session.timeRemaining <= 0) {
                        clearInterval(appState.session.timerInterval);
                        drillComplete();
                    }

                    saveState();
                }
            }, 1000);
        }

        // Update timer display
        function updateTimerDisplay() {
            const minutes = Math.floor(appState.session.timeRemaining / 60);
            const seconds = appState.session.timeRemaining % 60;
            document.getElementById('timerDisplay').textContent = 
                `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

            const progress = appState.session.totalTime > 0
                ? ((appState.session.totalTime - appState.session.timeRemaining) / appState.session.totalTime) * 100
                : 0;
            document.getElementById('timerProgressBar').style.width = progress + '%';
        }

        // Compute human-friendly drill times that sum to totalSeconds.
        // Strategy:
        // - Choose a sensible granularity based on the ideal per-drill time
        // - Round the ideal time to that granularity for each drill
        // - Distribute the remaining seconds in granularity-sized steps to drills closest to the ideal
        function computeDrillTimes(totalSeconds, count) {
            if (!count || count <= 0) return [];
            const ideal = totalSeconds / count;

            // Choose granularity
            let granularity = 10; // default 10s
            if (ideal < 30) granularity = 5;
            else if (ideal >= 30 && ideal < 60) granularity = 10;
            else if (ideal >= 60 && ideal < 180) granularity = 15;
            else granularity = 30;

            // Initial rounded times
            const times = Array.from({ length: count }, () => 0);
            for (let i = 0; i < count; i++) {
                times[i] = Math.max(granularity, Math.round(ideal / granularity) * granularity);
            }

            let sum = times.reduce((a, b) => a + b, 0);
            let diff = totalSeconds - sum;

            // Helper: compute indexes sorted by how suitable they are to receive adjustments
            const indexPriority = Array.from({ length: count }, (_, i) => i).sort((a, b) => {
                const da = Math.abs(times[a] - ideal);
                const db = Math.abs(times[b] - ideal);
                return da - db; // prefer altering those closest to ideal
            });

            // Apply adjustments in steps of granularity
            const step = granularity;
            while (diff !== 0) {
                if (Math.abs(diff) < step) {
                    // If remainder smaller than step, try to absorb it by adjusting a single item
                    const i = indexPriority[0];
                    times[i] += diff; // can be positive or negative
                    diff = 0;
                    break;
                }

                // Determine whether to add or subtract
                if (diff > 0) {
                    // need to add time: give to the drills that are most under ideal
                    let given = false;
                    for (const i of indexPriority) {
                        times[i] += step;
                        diff -= step;
                        given = true;
                        break;
                    }
                    if (!given) break;
                } else {
                    // need to remove time: remove from drills that are most above ideal but keep >= step
                    let removed = false;
                    for (const i of indexPriority.slice().reverse()) {
                        if (times[i] - step >= Math.max(5, step)) {
                            times[i] -= step;
                            diff += step;
                            removed = true;
                            break;
                        }
                    }
                    if (!removed) {
                        // can't remove in steps; break to avoid infinite loop
                        break;
                    }
                }
            }

            // Final safety: if rounding left a small discrepancy, fix by adjusting first/last
            let finalSum = times.reduce((a, b) => a + b, 0);
            let remaining = totalSeconds - finalSum;
            if (remaining !== 0) {
                // distribute the small remaining (can be positive or negative)
                for (let i = 0; i < count && remaining !== 0; i++) {
                    const delta = Math.abs(remaining) <= 1 ? remaining : Math.sign(remaining) * Math.min(Math.abs(remaining), 1);
                    times[i] += delta;
                    remaining -= delta;
                }
            }

            return times.map(t => Math.max(1, Math.round(t)));
        }

        // Skip current drill to end of time and immediately continue to next drill
        function skipToEnd() {
            try {
                if (appState.session.timerInterval) {
                    clearInterval(appState.session.timerInterval);
                }
            } catch (e) {}

            appState.session.timerInterval = null;
            appState.session.timerStarted = false;
            appState.session.timeRemaining = 0;
            updateTimerDisplay();
            saveState();

            // Advance to next drill
            nextDrill();
        }

        // Toggle pause
        function togglePause() {
            if (!appState.session.timerStarted) {
                return;
            }

            appState.session.isPaused = !appState.session.isPaused;
            document.getElementById('pauseBtn').textContent = appState.session.isPaused ? 'Resume' : 'Pause';
            document.getElementById('timerStatus').textContent = appState.session.isPaused
                ? 'Timer paused.'
                : 'Timer is running.';
            saveState();
        }

        // Drill complete
        function drillComplete() {
            appState.session.timerStarted = false;
            appState.session.timerInterval = null;
            document.getElementById('startTimerBtn').style.display = 'none';
            document.getElementById('pauseBtn').disabled = true;
            document.getElementById('timerStatus').textContent = 'Drill complete.';
            const skipBtnEl = document.getElementById('skipToEndBtn');
            if (skipBtnEl) skipBtnEl.style.display = 'none';
            document.getElementById('nextDrillContainer').style.display = 'block';
            saveState();
        }

        // Next drill
        function nextDrill() {
            appState.session.currentDrillIndex++;

            if (appState.session.currentDrillIndex >= appState.session.drills.length) {
                // Session complete
                sessionComplete();
            } else {
                loadCurrentDrill();
            }
        }

        // Session complete
        function sessionComplete() {
            if (appState.session.timerInterval) {
                clearInterval(appState.session.timerInterval);
            }

            document.getElementById('drillContent').classList.add('hidden');
            document.getElementById('sessionComplete').classList.remove('hidden');
        }

        // End session early
        function endSessionEarly() {
            if (confirm('Are you sure you want to end the session early?')) {
                if (appState.session.timerInterval) {
                    clearInterval(appState.session.timerInterval);
                }
                returnToSetup();
            }
        }

        // Return to setup
        function returnToSetup() {
            // Reset session
            appState.session = {
                currentDrillIndex: 0,
                drills: [],
                timerInterval: null,
                timeRemaining: 0,
                totalTime: 0,
                isPaused: false,
                timerStarted: false
            };

            // Show setup view
            document.getElementById('sessionView').classList.remove('active');
            document.getElementById('sessionComplete').classList.add('hidden');
            document.getElementById('setupView').style.display = 'block';
            document.getElementById('drillContent').classList.add('hidden');
            document.getElementById('loadingContainer').classList.remove('active');

            saveState();
        }

        // Save state to localStorage
        function saveState() {
            localStorage.setItem('cognicoach-state', JSON.stringify(appState));
        }

        // Load state from localStorage
        function loadState() {
            const saved = localStorage.getItem('cognicoach-state');
            if (saved) {
                try {
                    const loadedState = JSON.parse(saved);
                    
                    // Restore setup data
                    appState.setup = { ...appState.setup, ...loadedState.setup };
                    
                    // Restore form fields
                    if (loadedState.setup.sport) document.getElementById('sport').value = loadedState.setup.sport;
                    if (loadedState.setup.location) document.getElementById('location').value = loadedState.setup.location;
                    if (loadedState.setup.focus) document.getElementById('focus').value = loadedState.setup.focus;
                    if (loadedState.setup.muscleGroup) document.getElementById('muscleGroup').value = loadedState.setup.muscleGroup;
                    if (loadedState.setup.level) document.getElementById('level').value = loadedState.setup.level;
                    if (loadedState.setup.workoutLength) {
                        document.getElementById('workoutLength').value = loadedState.setup.workoutLength;
                        updateSliderValue();
                    }

                    // Restore session if active
                    if (loadedState.session && loadedState.session.drills && loadedState.session.drills.length > 0) {
                        appState.session = {
                            ...appState.session,
                            ...loadedState.session,
                            timerInterval: null
                        };
                        
                        // Show session view
                        document.getElementById('setupView').style.display = 'none';
                        document.getElementById('sessionView').classList.add('active');
                        
                        // Reload current drill
                        loadCurrentDrill();
                    }

                } catch (e) {
                    console.error('Error loading state:', e);
                }
            }
        }
        function initializeMuscleDiagramInteractions() {
            document.querySelectorAll(".muscle-groups #muscleSvgHost svg g g[id]").forEach(function(group) {
                const id = group.id.toLowerCase();
                group.addEventListener('mouseover', function() {
                    const label = document.querySelector(`.muscle-groups label[for="${id}"]`);
                    if (label) label.classList.add("hover");
                });
                group.addEventListener('mouseout', function() {
                    const label = document.querySelector(`.muscle-groups label[for="${id}"]`);
                    if (label) label.classList.remove("hover");
                });
                group.addEventListener('click', function(event) {
                    event.preventDefault();
                    toggleManualMuscle(id);
                });
            });

            document.querySelectorAll('.muscle-groups label[for]').forEach(function(label) {
                label.addEventListener('click', function(event) {
                    event.preventDefault();
                    toggleManualMuscle(label.htmlFor);
                });
            });
        }