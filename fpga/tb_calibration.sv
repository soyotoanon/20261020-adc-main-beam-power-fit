`timescale 1ns/1ps
module tb_calibration #(parameter FORMAT=0);
    reg clk=0, rst_n=0;
    always #10 clk=~clk;
    wire adc_clk, oeb, pdn, tx;
    reg [13:0] data=0;
    reg otr=0;
    calibration_top #(.WINDOW_SAMPLES(1024),.UART_DIV(4),.WARMUP_SAMPLES(12),.TWOS_COMPLEMENT(FORMAT))
        dut(clk,rst_n,data,otr,adc_clk,oeb,pdn,tx);
    // Mimic muxed bus with 6 ns output delay after each edge.
    always @(posedge adc_clk) begin #6; data=9000 ^ (FORMAT ? 8192 : 0); otr=0; end
    always @(negedge adc_clk) begin #6; data=7000 ^ (FORMAT ? 8192 : 0); otr=1; end
    integer f, i, bitn, packets=0;
    reg [7:0] value;
    initial begin
        f=$fopen(FORMAT ? "uart_signed_hex.txt" : "uart_hex.txt","w");
        #120; rst_n=1;
    end
    // Decode real UART pin, not internal payload.
    initial forever begin
        @(negedge tx);
        #120; // 1.5 UART bits, 80 ns each
        for(bitn=0;bitn<8;bitn=bitn+1) begin
            value[bitn]=tx;
            #80;
        end
        if(tx!==1) $fatal(1,"UART stop bit");
        $fwrite(f,"%02x\n",value);
        packets=packets+1;
        if(packets==180) begin
            $fclose(f);
            $display("TB_PASS: six UART frames captured");
            $finish;
        end
    end
    initial begin #2000000; $fatal(1,"Simulation timeout"); end
endmodule

module tb_calibration_signed;
    tb_calibration #(.FORMAT(1)) test_signed();
endmodule
