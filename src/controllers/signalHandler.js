const fs = require('fs');
const path = require('path');
const bitgetClient = require('../api/client');
const longPosition = require('./longPosition');
const shortPosition = require('./shortPosition');
const closePosition = require('./closePosition');

// 获取配置文件
const configPath = path.join(__dirname, '../../config.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

// 活跃交易文件路径
const tradesFilePath = path.join(__dirname, '../../data/active_trades.json');
// 设置文件路径
const settingsFilePath = path.join(__dirname, '../../data/settings.json');

/**
 * 获取当前交易设置
 * @returns {object} - 返回交易设置
 */
function getTradeSettings() {
  try {
    const settingsData = fs.readFileSync(settingsFilePath, 'utf8');
    return JSON.parse(settingsData);
  } catch (error) {
    console.error('读取设置失败，使用默认设置:', error);
    return {
      amount: config.trading.defaultAmount,
      leverage: config.trading.defaultLeverage,
      takeProfitPercentage: config.trading.defaultTakeProfitPercentage,
      stopLossPercentage: config.trading.defaultStopLossPercentage,
      tradeMode: config.trading.defaultTradeMode
    };
  }
}

/**
 * 检查是否允许开仓
 * @param {string} symbol - 交易对
 * @param {string} side - 交易方向
 * @returns {boolean} - 是否允许开仓
 */
function checkTradeAllowed(symbol, side) {
  try {
    const settings = getTradeSettings();
    const tradesData = fs.readFileSync(tradesFilePath, 'utf8');
    const trades = JSON.parse(tradesData);
    
    // 检查是否已有相同币种的仓位
    const existingTrade = trades.find(trade => trade.symbol === symbol);
    if (existingTrade) {
      console.log('已存在相同币种的仓位:', existingTrade);
      return false;
    }
    
    // 检查交易模式限制
    if (settings.tradeMode === 'long-only' && side === 'SELL') {
      console.log('当前为只做多模式，不允许做空');
      return false;
    }
    if (settings.tradeMode === 'short-only' && side === 'BUY') {
      console.log('当前为只做空模式，不允许做多');
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('检查交易许可失败:', error);
    return false;
  }
}

/**
 * 处理交易信号
 * @param {object} req - 请求对象
 * @param {object} res - 响应对象
 */
async function handleSignal(req, res) {
  try {
    const { COINNAME, SIDE } = req.body;
    
    if (!COINNAME || !SIDE) {
      return res.status(400).json({ success: false, message: '缺少必要参数' });
    }
    
    // 获取当前设置
    const settings = getTradeSettings();
    console.log('\n收到交易信号:');
    console.log('------------------------');
    console.log('交易对:', COINNAME);
    console.log('方向:', SIDE);
    console.log('交易金额:', settings.amount, 'USDT');
    console.log('杠杆倍数:', settings.leverage, 'x');
    console.log('实际交易金额:', settings.amount * settings.leverage, 'USDT');
    console.log('止盈比例:', settings.takeProfitPercentage, '%');
    console.log('止损比例:', settings.stopLossPercentage, '%');
    console.log('------------------------\n');
    
    // 检查是否允许交易
    if (!checkTradeAllowed(COINNAME, SIDE)) {
      return res.status(400).json({ 
        success: false, 
        message: '不允许开仓，可能是因为已有相同币种的仓位或违反交易模式限制' 
      });
    }
    
    // 根据信号执行交易
    let result;
    if (SIDE === 'BUY') {
      result = await longPosition.openLong({
        body: {
          symbol: COINNAME,
          amount: settings.amount,
          leverage: settings.leverage,
          takeProfitPercentage: settings.takeProfitPercentage,
          stopLossPercentage: settings.stopLossPercentage
        }
      });
    } else if (SIDE === 'SELL') {
      result = await shortPosition.openShort({
        body: {
          symbol: COINNAME,
          amount: settings.amount,
          leverage: settings.leverage,
          takeProfitPercentage: settings.takeProfitPercentage,
          stopLossPercentage: settings.stopLossPercentage
        }
      });
    } else {
      return res.status(400).json({ success: false, message: '无效的交易方向' });
    }
    
    res.json(result);
  } catch (error) {
    console.error('处理交易信号失败:', error);
    res.status(500).json({ success: false, message: '处理交易信号失败', error: error.message });
  }
}

module.exports = {
  handleSignal
}; 