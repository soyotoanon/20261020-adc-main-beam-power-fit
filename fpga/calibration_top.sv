`timescale 1ns/1ps
// New standalone design: 50 MHz -> 5 MHz ADC, 115200 8N1 UART.
// ADC raw code is preserved. No PID, DAC control, old IP or source dependencies.
module calibration_top #(
    parameter integer WINDOW_SAMPLES = 262144,
    parameter integer UART_DIV = 434,
    parameter integer WARMUP_SAMPLES = 50000,
    parameter integer TWOS_COMPLEMENT = 1
)(
    input wire sys_clk, input wire sys_rst_n,
    input wire [13:0] adc_d, input wire adc_otr,
    output reg adc_clk = 0,
    output wire adc_oeb_n, output wire adc_pdn,
    output wire uart_txd
);
    assign adc_oeb_n = 1'b0;
    assign adc_pdn = 1'b0;
    (* ASYNC_REG = "TRUE" *) reg [1:0] reset_sync = 0;
    always @(posedge sys_clk or negedge sys_rst_n)
        if (!sys_rst_n) reset_sync <= 0;
        else reset_sync <= {reset_sync[0],1'b1};
    wire reset = !reset_sync[1];
    reg [3:0] phase = 0;
    reg [31:0] warmup = 0;
    // All logic stays in sys_clk. Capture 60 ns after each clock edge:
    // phase 3 / phase 8. These are candidate channels, not verified INA/INB.
    (* IOB = "TRUE" *) reg [13:0] captured = 0;
    (* IOB = "TRUE" *) reg captured_otr = 0;
    reg valid = 0;
    reg channel = 0;
    always @(posedge sys_clk) begin
        valid <= 0;
        if (reset) begin
            phase <= 0; adc_clk <= 0; warmup <= 0;
            captured <= 0; captured_otr <= 0;
        end else begin
            phase <= phase == 9 ? 0 : phase+1'b1;
            if (phase == 0) adc_clk <= 1;
            if (phase == 5) adc_clk <= 0;
            if (phase == 3 || phase == 8) begin
                captured <= adc_d ^ (TWOS_COMPLEMENT ? 14'h2000 : 14'h0000);
                captured_otr <= adc_otr;
                channel <= phase == 8;
                if (warmup < WARMUP_SAMPLES) begin
                    if (phase == 8) warmup <= warmup+1;
                end
                else valid <= 1;
            end
        end
    end

    reg [31:0] count [0:1], total [0:1], sequence_id [0:1];
    reg [63:0] squares [0:1];
    reg [13:0] minimum [0:1], maximum [0:1];
    reg overflow [0:1], rail [0:1];
    reg [223:0] pending_payload [0:1];
    reg [1:0] pending = 0;
    integer i;
    wire [27:0] square = captured * captured;
    wire [31:0] next_total = total[channel] + {18'b0,captured};
    wire [63:0] next_squares = squares[channel] + {36'b0,square};
    wire [13:0] next_min = captured < minimum[channel] ? captured : minimum[channel];
    wire [13:0] next_max = captured > maximum[channel] ? captured : maximum[channel];
    wire [7:0] flags = {4'b0, (TWOS_COMPLEMENT!=0), channel,
                          (rail[channel] || captured==0 || captured==16383),
                          (overflow[channel] || captured_otr)};
    reg [223:0] payload = 0;
    reg sending = 0;
    reg [5:0] byte_index = 0;
    reg [15:0] crc = 16'hffff;
    reg [7:0] tx_data = 0;
    reg tx_start = 0;
    wire tx_busy;
    reg wait_busy = 0;
    function automatic [15:0] crc_byte(input [15:0] old_crc, input [7:0] data);
        reg [15:0] c;
        integer k;
        begin
            c = old_crc ^ {data,8'b0};
            for (k=0; k<8; k=k+1)
                c = c[15] ? (c << 1)^16'h1021 : c << 1;
            crc_byte = c;
        end
    endfunction
    uart_tx #(.DIV(UART_DIV)) serial(sys_clk,reset,tx_start,tx_data,uart_txd,tx_busy);
    always @(posedge sys_clk) begin
        tx_start <= 0;
        if (reset) begin
            for (i=0;i<2;i=i+1) begin
                count[i]<=0; total[i]<=0; squares[i]<=0; sequence_id[i]<=0;
                minimum[i]<=16383; maximum[i]<=0; overflow[i]<=0; rail[i]<=0;
                pending_payload[i]<=0;
            end
            pending<=0;
            payload<=0; sending<=0; byte_index<=0; crc<=16'hffff;
            tx_data<=0; wait_busy<=0;
        end else begin
            if (!sending && !tx_busy && !tx_start && !wait_busy && |pending) begin
                if (pending[0]) begin payload<=pending_payload[0]; pending[0]<=0; end
                else begin payload<=pending_payload[1]; pending[1]<=0; end
                sending<=1; byte_index<=0; crc<=16'hffff;
            end
            if (valid) begin
                if (count[channel] == WINDOW_SAMPLES-1) begin
                    // Whole-window drop on congestion; per-channel sequence exposes loss.
                    if (!pending[channel]) begin
                        pending_payload[channel] <= {32'(WINDOW_SAMPLES),2'b0,next_max,2'b0,next_min,
                                    next_squares,next_total,sequence_id[channel],flags,8'h01,8'h43,8'h50};
                        pending[channel]<=1;
                    end
                    sequence_id[channel]<=sequence_id[channel]+1;
                    count[channel]<=0; total[channel]<=0; squares[channel]<=0;
                    minimum[channel]<=16383; maximum[channel]<=0;
                    overflow[channel]<=0; rail[channel]<=0;
                end else begin
                    count[channel]<=count[channel]+1; total[channel]<=next_total;
                    squares[channel]<=next_squares;
                    minimum[channel]<=next_min; maximum[channel]<=next_max;
                    overflow[channel]<=overflow[channel]|captured_otr;
                    rail[channel]<=rail[channel]|(captured==0)|(captured==16383);
                end
            end
            if (wait_busy) begin
                if (tx_busy) wait_busy<=0;
            end else if (sending && !tx_busy && !tx_start) begin
                if (byte_index < 28) begin
                    tx_data<=payload[byte_index*8 +: 8];
                    crc<=crc_byte(crc,payload[byte_index*8 +: 8]);
                end else if (byte_index == 28) tx_data<=crc[7:0];
                else tx_data<=crc[15:8];
                tx_start<=1; wait_busy<=1;
                if (byte_index==29) sending<=0;
                else byte_index<=byte_index+1;
            end
        end
    end
endmodule

module uart_tx #(parameter integer DIV=434)(
    input wire clk, input wire reset, input wire start, input wire [7:0] data,
    output wire tx, output reg busy=0
);
    reg [9:0] shift=10'h3ff;
    reg [31:0] timer=0;
    reg [3:0] bit_index=0;
    assign tx=shift[0];
    always @(posedge clk) begin
        if (reset) begin shift<=10'h3ff; timer<=0; bit_index<=0; busy<=0; end
        else if (!busy) begin
            if (start) begin
                shift<={1'b1,data,1'b0}; timer<=DIV-1; bit_index<=0; busy<=1;
            end
        end else if (timer!=0) timer<=timer-1;
        else begin
            shift<={1'b1,shift[9:1]}; timer<=DIV-1;
            if (bit_index==9) busy<=0;
            else bit_index<=bit_index+1;
        end
    end
endmodule
