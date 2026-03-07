async function queryWithStreaming(query, connId) {
    const response = await fetch('/api/v1/agent/query-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, connection_id: connId })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    // Show loading state immediately
    if (typeof updateUI === 'function') {
        updateUI({ status: 'Parsing intent...', step: 'parse_intent' });
    } else {
        console.log('Parsing intent...', 'parse_intent');
    }

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value);
        const lines = text.split('\n').filter(l => l.startsWith('data:'));

        for (const line of lines) {
            const dataText = line.slice(6);
            if (!dataText.trim()) continue;

            try {
                const data = JSON.parse(dataText);

                // Update UI for each step
                if (typeof updateUI === 'function') {
                    updateUI({
                        status: `${data.node} completed`,
                        step: data.node,
                        data: data.data
                    });
                } else {
                    console.log(`${data.node} completed`, data);
                }
            } catch (e) {
                console.error("Error parsing streaming JSON", e, dataText);
            }
        }
    }
}
