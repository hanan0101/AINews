function initNeuralNetworkCanvas(canvasId = 'splashNeuralCanvas'){
    const canvas = document.getElementById(canvasId);
    if(!canvas) return;
    const ctx = canvas.getContext('2d');
    let W = 0;
    let H = 0;
    let nodes = [];
    let running = true;
    let tick = 0;
    const COUNT = 68;
    const MAX_DIST = 155;

    function resize(){
      const panel = canvas.parentElement;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = panel?.offsetWidth || window.innerWidth;
      H = panel?.offsetHeight || window.innerHeight;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function init(){
      nodes = Array.from({length: COUNT}, () => ({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.42,
        vy: (Math.random() - 0.5) * 0.42,
        r: Math.random() * 2.2 + 1.35,
        phase: Math.random() * Math.PI * 2
      }));
    }

    function frame(){
      if(!running) return;
      ctx.clearRect(0, 0, W, H);
      tick += 0.018;
      nodes.forEach(node => {
        node.x += node.vx;
        node.y += node.vy;
        if(node.x < 0 || node.x > W) node.vx *= -1;
        if(node.y < 0 || node.y > H) node.vy *= -1;
      });

      for(let i = 0; i < nodes.length; i++){
        for(let j = i + 1; j < nodes.length; j++){
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if(d < MAX_DIST){
            const strength = 1 - d / MAX_DIST;
            const pulse = 0.72 + Math.sin(tick + nodes[i].phase + nodes[j].phase) * 0.28;
            ctx.beginPath();
            ctx.strokeStyle = `rgba(199,61,57,${strength * pulse * 0.30})`;
            ctx.lineWidth = 0.65 + strength * 0.75;
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      nodes.forEach(node => {
        const pulse = 0.76 + Math.sin(tick * 1.6 + node.phase) * 0.24;
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.r * pulse, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(199,61,57,0.44)';
        ctx.shadowColor = 'rgba(199,61,57,0.16)';
        ctx.shadowBlur = 5;
        ctx.fill();
        ctx.shadowBlur = 0;
      });
      requestAnimationFrame(frame);
    }

    resize();
    init();
    frame();
    window.addEventListener('resize', () => {
      resize();
      init();
    });
    return () => { running = false; };
  }
  initNeuralNetworkCanvas('splashNeuralCanvas');
