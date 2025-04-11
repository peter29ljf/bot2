const express = require('express');
const path = require('path');
const fs = require('fs');
const bodyParser = require('body-parser');
const signalHandler = require('./src/controllers/signalHandler');
const longPosition = require('./src/controllers/longPosition');
const shortPosition = require('./src/controllers/shortPosition');
const closePosition = require('./src/controllers/closePosition');
const monitor = require('./src/controllers/monitor');
const bitgetClient = require('./src/api/client');

const app = express();
const PORT = process.env.PORT || 3000;

// 启动前设置持仓模式
async function initializeServer() {
  try {
    console.log('正在设置持仓模式...');
    const result = await bitgetClient.setPositionMode('single_hold');
    console.log('持仓模式设置结果:', result);
  } catch (error) {
    console.error('设置持仓模式失败:', error);
  }

  // 启动监控系统
  monitor.start();

  // 启动服务器
  app.listen(PORT, () => {
    console.log(`服务器已启动: http://localhost:${PORT}`);
  });
}

// 中间件
app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public')));

// 确保数据目录存在
const dataDir = path.join(__dirname, 'data');
if (!fs.existsSync(dataDir)) {
  fs.mkdirSync(dataDir);
}

// 确保active_trades.json文件存在
const tradesFilePath = path.join(dataDir, 'active_trades.json');
if (!fs.existsSync(tradesFilePath)) {
  fs.writeFileSync(tradesFilePath, JSON.stringify([]));
}

// 获取当前活跃交易
app.get('/api/trades', (req, res) => {
  try {
    const tradesData = fs.readFileSync(tradesFilePath, 'utf8');
    const trades = JSON.parse(tradesData);
    res.json(trades);
  } catch (error) {
    console.error('获取交易信息失败:', error);
    res.status(500).json({ success: false, message: '获取交易信息失败' });
  }
});

// 信号处理路由
app.post('/api/signal', signalHandler.handleSignal);

// 开多仓位
app.post('/api/open-long', longPosition.openLong);

// 开空仓位
app.post('/api/open-short', shortPosition.openShort);

// 平仓操作
app.post('/api/close-position', closePosition.closePosition);

// API状态检查
app.get('/api/status', (req, res) => {
  try {
    // 获取活跃交易数量
    const tradesData = fs.readFileSync(tradesFilePath, 'utf8');
    const trades = JSON.parse(tradesData);
    
    // 检查API连接状态
    const apiConnected = true; // 可以改为实际检查API连接状态的逻辑
    
    res.json({ 
      success: true, 
      apiConnected: apiConnected,
      isTestMode: process.env.TEST_MODE === 'true' || true,
      activeTrades: trades.length
    });
  } catch (error) {
    console.error('获取API状态失败:', error);
    res.status(500).json({ success: false, message: '获取API状态失败' });
  }
});

// 保存设置
app.post('/api/settings', (req, res) => {
  try {
    const settings = req.body;
    console.log('\n收到新的设置参数:');
    console.log('------------------------');
    console.log('交易金额:', settings.amount, 'USDT');
    console.log('杠杆倍数:', settings.leverage, 'x');
    console.log('止盈比例:', settings.takeProfitPercentage, '%');
    console.log('止损比例:', settings.stopLossPercentage, '%');
    console.log('交易模式:', settings.tradeMode);
    console.log('------------------------\n');

    fs.writeFileSync(path.join(dataDir, 'settings.json'), JSON.stringify(settings, null, 2));
    console.log('设置已保存到文件');
    res.json({ success: true, message: '设置已保存' });
  } catch (error) {
    console.error('保存设置失败:', error);
    res.status(500).json({ success: false, message: '保存设置失败' });
  }
});

// 获取设置
app.get('/api/settings', (req, res) => {
  try {
    const settingsPath = path.join(dataDir, 'settings.json');
    if (!fs.existsSync(settingsPath)) {
      const defaultSettings = {
        amount: 40,
        leverage: 25,
        takeProfitPercentage: 5,
        stopLossPercentage: 5,
        tradeMode: 'both'
      };
      fs.writeFileSync(settingsPath, JSON.stringify(defaultSettings, null, 2));
      console.log('\n创建默认设置:');
      console.log('------------------------');
      console.log('交易金额:', defaultSettings.amount, 'USDT');
      console.log('杠杆倍数:', defaultSettings.leverage, 'x');
      console.log('止盈比例:', defaultSettings.takeProfitPercentage, '%');
      console.log('止损比例:', defaultSettings.stopLossPercentage, '%');
      console.log('交易模式:', defaultSettings.tradeMode);
      console.log('------------------------\n');
      res.json(defaultSettings);
    } else {
      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
      console.log('\n读取当前设置:');
      console.log('------------------------');
      console.log('交易金额:', settings.amount, 'USDT');
      console.log('杠杆倍数:', settings.leverage, 'x');
      console.log('止盈比例:', settings.takeProfitPercentage, '%');
      console.log('止损比例:', settings.stopLossPercentage, '%');
      console.log('交易模式:', settings.tradeMode);
      console.log('------------------------\n');
      res.json(settings);
    }
  } catch (error) {
    console.error('获取设置失败:', error);
    res.status(500).json({ success: false, message: '获取设置失败' });
  }
});

// 平仓特定交易
app.post('/api/close/:tradeId', async (req, res) => {
  try {
    const tradeId = req.params.tradeId;
    
    // 读取活跃交易
    const tradesData = fs.readFileSync(tradesFilePath, 'utf8');
    let trades = JSON.parse(tradesData);
    
    // 找到要平仓的交易
    const tradeIndex = trades.findIndex(trade => trade.orderId === tradeId);
    if (tradeIndex === -1) {
      return res.status(404).json({ success: false, message: '未找到该交易' });
    }
    
    const trade = trades[tradeIndex];
    
    // 调用平仓逻辑
    let result;
    if (trade.type === 'long' || trade.type === 'dual_long') {
      result = await closePosition.closeLongPosition(trade.symbol, trade.size);
    } else if (trade.type === 'short' || trade.type === 'dual_short') {
      result = await closePosition.closeShortPosition(trade.symbol, trade.size);
    } else {
      return res.status(400).json({ success: false, message: '不支持的交易类型' });
    }
    
    if (result && result.success) {
      // 从活跃交易列表中移除
      trades.splice(tradeIndex, 1);
      fs.writeFileSync(tradesFilePath, JSON.stringify(trades, null, 2));
      
      res.json({ success: true, message: '平仓成功' });
    } else {
      res.status(400).json({ success: false, message: result.message || '平仓失败' });
    }
  } catch (error) {
    console.error('平仓失败:', error);
    res.status(500).json({ success: false, message: '平仓操作失败' });
  }
});

// 初始化并启动服务器
initializeServer(); 