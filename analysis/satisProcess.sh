# Process all 12 simulations: 3 periods x 2 mpc x 2 vut

# WITH VUT (VUT60)
echo "Processing withVUT scenarios..."
python satis.py --folder ../results --seed 0 --begin 2 --end 4 --fromt "3:00"    --mpcInterval 5 --vut 60 --aggregation 20 --nick opt
python satis.py --folder ../results --seed 0 --begin 11 --end 13 --fromt "12:00" --mpcInterval 5 --vut 60 --aggregation 20 --nick opt
python satis.py --folder ../results --seed 0 --begin 16 --end 18 --fromt "17:00" --mpcInterval 5 --vut 60 --aggregation 20 --nick opt

python satis.py --folder ../results --seed 0 --begin 2 --end 4 --fromt "3:00"    --mpcInterval -5 --vut 60 --aggregation 20 --nick benchmark
python satis.py --folder ../results --seed 0 --begin 11 --end 13 --fromt "12:00" --mpcInterval -5 --vut 60 --aggregation 20 --nick benchmark
python satis.py --folder ../results --seed 0 --begin 16 --end 18 --fromt "17:00" --mpcInterval -5 --vut 60 --aggregation 20 --nick benchmark

# WITHOUT VUT (VUT0)
echo "Processing noVUT scenarios..."
python satis.py --folder ../results --seed 0 --begin 2 --end 4 --fromt "3:00"    --mpcInterval 5 --vut 0 --aggregation 20 --nick opt
python satis.py --folder ../results --seed 0 --begin 11 --end 13 --fromt "12:00" --mpcInterval 5 --vut 0 --aggregation 20 --nick opt
python satis.py --folder ../results --seed 0 --begin 16 --end 18 --fromt "17:00" --mpcInterval 5 --vut 0 --aggregation 20 --nick opt

python satis.py --folder ../results --seed 0 --begin 2 --end 4 --fromt "3:00"    --mpcInterval -5 --vut 0 --aggregation 20 --nick benchmark
python satis.py --folder ../results --seed 0 --begin 11 --end 13 --fromt "12:00" --mpcInterval -5 --vut 0 --aggregation 20 --nick benchmark
python satis.py --folder ../results --seed 0 --begin 16 --end 18 --fromt "17:00" --mpcInterval -5 --vut 0 --aggregation 20 --nick benchmark

mv satis*parquet parquets
