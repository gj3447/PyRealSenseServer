// 스트림 상태
let isStreaming = false;

// 스트림 시작
async function startStream() {
    if (isStreaming) return;
    
    try {
        const response = await fetch('/camera/start', { method: 'POST' });
        if (response.ok) {
            isStreaming = true;
            updateStreamUI(true);
            // 여기에 스트림 표시 로직 추가
        }
    } catch (error) {
        console.error('스트림 시작 실패:', error);
    }
}

// 스트림 중지
async function stopStream() {
    if (!isStreaming) return;
    
    try {
        const response = await fetch('/camera/stop', { method: 'POST' });
        if (response.ok) {
            isStreaming = false;
            updateStreamUI(false);
        }
    } catch (error) {
        console.error('스트림 중지 실패:', error);
    }
}

// 포인트 클라우드 생성
async function generatePointCloud() {
    try {
        const response = await fetch('/pointcloud/generate', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            console.log('포인트 클라우드 생성됨:', data);
            // 여기에 포인트 클라우드 표시 로직 추가
        }
    } catch (error) {
        console.error('포인트 클라우드 생성 실패:', error);
    }
}

// UI 업데이트
function updateStreamUI(isActive) {
    const streamElement = document.getElementById('camera-stream');
    const statusElement = document.getElementById('connection-status');
    
    if (isActive) {
        streamElement.innerHTML = '<p class="text-gray-500">스트리밍 중...</p>';
        statusElement.textContent = '스트리밍 중';
        statusElement.classList.remove('text-red-500');
        statusElement.classList.add('text-green-500');
    } else {
        streamElement.innerHTML = '<p class="text-gray-500">스트림 중지됨</p>';
        statusElement.textContent = '중지됨';
        statusElement.classList.remove('text-green-500');
        statusElement.classList.add('text-red-500');
    }
}

// 설정 변경 이벤트 리스너
document.getElementById('depth-mode').addEventListener('change', async (e) => {
    try {
        const response = await fetch('/camera/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ depth_mode: e.target.value })
        });
        if (!response.ok) throw new Error('설정 변경 실패');
    } catch (error) {
        console.error('깊이 모드 변경 실패:', error);
    }
});

document.getElementById('color-mode').addEventListener('change', async (e) => {
    try {
        const response = await fetch('/camera/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ color_mode: e.target.value })
        });
        if (!response.ok) throw new Error('설정 변경 실패');
    } catch (error) {
        console.error('컬러 모드 변경 실패:', error);
    }
}); 